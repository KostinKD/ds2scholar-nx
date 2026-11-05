// ds2scholar-nx - native renderer: vertex ranges kept across frames (ds2_vertex_cache_mb).
//
// The problem, measured
// ---------------------
// Every draw copies the [vmin..vmax] range of each vertex binding into the upload buffer, byte-swapped, and the upload
// buffer is reset at every work slot. DedupeVertices (sa2_native_vertices_dedupe.h) only reuses a copy within the same
// slot. SotFS on the console (Majula, 540p uncapped, 2026-10-23): ~870 vertex lookups a frame, ~390 copied again; on
// the ring thread CopyVertices + memmove ~17 % and the fingerprints ~9 % (prof_uncapped_v1). sa2-nx measured on PC
// that 51-59 % of the bytes equal a copy made in an earlier frame.
//
// What this does
// --------------
// A persistent host-visible buffer (the upload buffer's memory type) split into kChunks chunks. A range is identified
// by (physical address, byte order, bytes) and validated by a content fingerprint of the guest bytes, taken on every
// lookup (the caller chooses full XXH3 or the sampled one, ds2_vertex_cache_hash). The same fingerprint as when it was
// copied -> the draw binds the cached copy and nothing is copied.
//
//   - Admission on the second sighting: a range is copied into the cache only when it is seen again with the same
//     fingerprint in a later work slot. One-off data (written once and drawn once) never takes cache space.
//   - Ranges whose content keeps changing (skinned meshes, particles) are marked dynamic after two changes and take
//     the usual path; eight unchanged sightings in a row make them eligible again.
//   - A changed range never overwrites its old copy (the GPU may still read it): it is copied to new space.
//   - Within one work slot and one guest synchronization epoch (g_synchronizations_ring) a range already validated
//     is not fingerprinted again (Fast): on the Xbox 360 the game cannot rewrite a range a pending draw reads without
//     synchronizing with the GPU first, the guarantee the in-frame dedupe and the index cache rely on. Console profile
//     with the cache: the fingerprints were 18.5 % of the ring thread, one per lookup.
//   - Space is a bump allocator per chunk. When the current chunk is full the next one is recycled, but only when no
//     submission that may still be on the GPU used it: its last use is at least kGuardEpochs work slots old. A chunk
//     that cannot be recycled yet is retired (no more hits from it), so it becomes recyclable after kGuardEpochs slots;
//     its live ranges are copied again into the current chunk when next drawn.
//
// Epochs are the renderer's epoch_upload_ (one per UseSlot). BeginRecording waits for a slot's previous submission
// before UseSlot, and slots rotate over at most kSlotsOfWork = 3, so every submission at least 3 epochs old has
// finished; kGuardEpochs = 4 keeps one more of margin.
//
// Single thread (the ring thread). No Vulkan here: the renderer owns the buffer and copies the bytes.

#pragma once

#include <array>
#include <cstdint>
#include <vector>

namespace sa2::native {

class VertexCache {
 public:
  static constexpr uint32_t kChunks = 8;
  static constexpr uint64_t kGuardEpochs = 4;
  static constexpr size_t kSlots = 131072;  // entries of the lookup table (power of 2); 32768 replaced ~85k a 10 s on PC

  enum class Result {
    kMiss,  // not in the cache: the usual path (upload buffer)
    kHit,   // the cached copy at `offset` is valid: bind it, copy nothing
    kCopy,  // space reserved at `offset`: the caller copies the range there now and binds it
  };

  void Init(uint64_t size) {
    chunk_size_ = size / kChunks & ~uint64_t(255);
    for (uint32_t c = 0; c < kChunks; ++c) {
      chunks_[c] = Chunk{};
      chunks_[c].base = uint64_t(c) * chunk_size_;
    }
    current_ = 0;
    table_.assign(kSlots, Entry{});
  }
  uint64_t chunk_size() const { return chunk_size_; }

  // A range validated in this work slot and synchronization epoch: bound without a fingerprint.
  bool Fast(uint64_t address, uint32_t order, uint32_t bytes, uint64_t epoch, uint32_t sync, uint64_t& offset) {
    const uint64_t key = (address << 2) | (uint64_t(order) & 0x3);
    Entry& e = table_[Index(key, bytes)];
    if (!e.used || e.key != key || e.bytes != bytes || !e.admitted || e.valid_epoch != epoch ||
        e.valid_sync != sync || chunks_[e.chunk].generation != e.generation || chunks_[e.chunk].retired) {
      return false;
    }
    ++lookups_;
    ++hits_;
    ++fast_hits_;
    bytes_saved_ += bytes;
    chunks_[e.chunk].last_epoch = epoch;
    offset = e.offset;
    return true;
  }

  // `multiple`: alignment of a new copy (the stride for the base-zero path, else 4).
  Result Lookup(uint64_t address, uint32_t order, uint32_t bytes, uint64_t fingerprint, uint32_t multiple,
                uint64_t epoch, uint32_t sync, uint64_t& offset) {
    ++lookups_;
    const uint64_t key = (address << 2) | (uint64_t(order) & 0x3);
    Entry& e = table_[Index(key, bytes)];
    if (e.key != key || e.bytes != bytes || !e.used) {
      if (e.used) ++replaced_;
      e = Entry{};
      e.used = true;
      e.key = key;
      e.bytes = bytes;
      e.fingerprint = fingerprint;
      e.seen_epoch = epoch;
      ++first_sightings_;
      return Result::kMiss;
    }
    if (e.fingerprint != fingerprint) {
      e.fingerprint = fingerprint;
      e.admitted = false;
      e.stable = 0;
      e.seen_epoch = epoch;
      if (e.changes < 255) ++e.changes;
      if (e.changes >= 2 && !e.dynamic) {
        e.dynamic = true;
        ++became_dynamic_;
      }
      ++changed_;
      return Result::kMiss;
    }
    if (e.admitted && chunks_[e.chunk].generation == e.generation && !chunks_[e.chunk].retired) {
      chunks_[e.chunk].last_epoch = epoch;
      ++hits_;
      bytes_saved_ += bytes;
      e.valid_epoch = epoch;
      e.valid_sync = sync;
      offset = e.offset;
      return Result::kHit;
    }
    if (e.dynamic) {
      if (++e.stable < 8) {
        ++dynamic_misses_;
        return Result::kMiss;
      }
      e.dynamic = false;
      e.changes = 0;
    }
    // Admitted earlier but its chunk was recycled or retired: it is known to be stable, copy it again now.
    if (!e.admitted && e.seen_epoch == epoch) {
      return Result::kMiss;  // the second sighting must come from a later work slot
    }
    uint64_t at = 0;
    if (!Allocate(bytes, multiple, epoch, at)) {
      ++full_;
      return Result::kMiss;
    }
    e.admitted = true;
    e.offset = at;
    e.chunk = uint8_t(current_);
    e.generation = chunks_[current_].generation;
    e.valid_epoch = epoch;
    e.valid_sync = sync;
    ++copies_;
    bytes_copied_ += bytes;
    offset = at;
    return Result::kCopy;
  }

  // Verification (ds2_vertex_cache_verify): a second, full fingerprint stored with the copy and compared on hits.
  void NoteFull(uint64_t address, uint32_t order, uint32_t bytes, uint64_t full) {
    Entry& e = table_[Index((address << 2) | (uint64_t(order) & 0x3), bytes)];
    e.full = full;
  }
  bool CheckFull(uint64_t address, uint32_t order, uint32_t bytes, uint64_t full) {
    const Entry& e = table_[Index((address << 2) | (uint64_t(order) & 0x3), bytes)];
    ++verified_;
    if (e.full == full) return true;
    ++stale_;
    return false;
  }
  // A hit refused by the verification: the entry is dropped so the range is copied again.
  void Drop(uint64_t address, uint32_t order, uint32_t bytes) {
    Entry& e = table_[Index((address << 2) | (uint64_t(order) & 0x3), bytes)];
    e.admitted = false;
    e.fingerprint = 0;
  }

  struct Figures {
    uint64_t lookups, hits, fast_hits, bytes_saved, copies, bytes_copied, first_sightings, changed, became_dynamic,
        dynamic_misses, full, replaced, recycled, retired, verified, stale;
  };
  Figures figures() const {
    return {lookups_, hits_, fast_hits_, bytes_saved_, copies_, bytes_copied_, first_sightings_, changed_, became_dynamic_,
            dynamic_misses_, full_, replaced_, recycled_, retired_, verified_, stale_};
  }

 private:
  struct Entry {
    uint64_t key = 0;          // (address << 2) | order
    uint64_t fingerprint = 0;  // of the guest bytes at the last sighting
    uint64_t full = 0;         // ds2_vertex_cache_verify only
    uint64_t offset = 0;       // in the cache buffer
    uint64_t seen_epoch = 0;   // first sighting with this fingerprint
    uint64_t valid_epoch = ~uint64_t(0);  // work slot of the last validation (Fast)
    uint32_t valid_sync = 0;              // g_synchronizations_ring at that validation
    uint32_t bytes = 0;
    uint32_t generation = 0;   // of the chunk when copied
    uint8_t chunk = 0;
    uint8_t changes = 0;
    uint8_t stable = 0;
    bool used = false;
    bool admitted = false;
    bool dynamic = false;
  };
  struct Chunk {
    uint64_t base = 0;
    uint64_t used = 0;
    uint64_t last_epoch = 0;  // last work slot that bound a range in it
    uint32_t generation = 1;
    bool retired = false;
  };

  bool Allocate(uint32_t bytes, uint32_t multiple, uint64_t epoch, uint64_t& offset) {
    if (!multiple) multiple = 4;
    if (uint64_t(bytes) + multiple > chunk_size_) return false;
    for (int attempt = 0; attempt < 2; ++attempt) {
      Chunk& c = chunks_[current_];
      const uint64_t start = (c.base + c.used + multiple - 1) / multiple * multiple;
      if (start + bytes <= c.base + chunk_size_) {
        c.used = start + bytes - c.base;
        c.last_epoch = epoch;
        offset = start;
        return true;
      }
      const uint32_t next = (current_ + 1) % kChunks;
      Chunk& n = chunks_[next];
      if (n.last_epoch + kGuardEpochs > epoch) {
        if (!n.retired) {
          n.retired = true;  // no more hits from it: recyclable kGuardEpochs slots from now
          ++retired_;
        }
        return false;
      }
      ++n.generation;
      n.used = 0;
      n.retired = false;
      n.last_epoch = epoch;
      current_ = next;
      ++recycled_;
    }
    return false;
  }

  static size_t Index(uint64_t key, uint32_t bytes) {
    uint64_t x = key ^ (uint64_t(bytes) * 0x9E3779B97F4A7C15ull);
    x ^= x >> 30;
    x *= 0xBF58476D1CE4E5B9ull;
    x ^= x >> 27;
    return size_t(x) & (kSlots - 1);
  }

  std::array<Chunk, kChunks> chunks_{};
  uint32_t current_ = 0;
  uint64_t chunk_size_ = 0;
  std::vector<Entry> table_;

  uint64_t lookups_ = 0, hits_ = 0, fast_hits_ = 0, bytes_saved_ = 0, copies_ = 0, bytes_copied_ = 0, first_sightings_ = 0,
           changed_ = 0, became_dynamic_ = 0, dynamic_misses_ = 0, full_ = 0, replaced_ = 0, recycled_ = 0,
           retired_ = 0, verified_ = 0, stale_ = 0;
};

}  // namespace sa2::native
