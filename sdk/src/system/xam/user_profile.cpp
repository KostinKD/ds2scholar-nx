/**
 ******************************************************************************
 * Xenia : Xbox 360 Emulator Research Project                                 *
 ******************************************************************************
 * Copyright 2020 Ben Vanik. All rights reserved.                             *
 * Released under the BSD license - see LICENSE in the root for more details. *
 ******************************************************************************
 *
 * @modified    Tom Clay, 2026 - Adapted for ReXGlue runtime
 */

#include <cctype>
#include <vector>
#include <cstdio>
#include <cerrno>
#include <filesystem>
#include <fstream>
#include <random>
#include <sstream>
#include <string_view>

#include <fmt/format.h>

#include <rex/cvar.h>
#include <rex/platform.h>
#include <rex/logging.h>
#include <rex/system/kernel_state.h>
#include <rex/system/xam/gamertag.h>
#include <rex/system/xam/user_profile.h>

// Two PC instances otherwise share both the server account and the content namespace.
// Zero keeps the historical profile; overrides are startup-only, just like UserProfile.
REXCVAR_DEFINE_UINT64(net_profile_xuid, 0, "Net",
                     "Experimental local profile XUID for separate online clients; 0 keeps the default profile");

REXCVAR_DEFINE_BOOL(net_profile_generate_xuid, false, "Net",
                    "Own XUID: on the Switch from the user account (hashed), elsewhere random and kept in "
                    "<user data>/profile_identity.txt; the saves of the default XUID are copied to it once. "
                    "net_profile_xuid still wins. false = the default XUID");
REXCVAR_DEFINE_STRING(net_profile_name, "", "Net",
                      "Gamertag shown online (letters, digits, space, _ - .; up to 15; Cyrillic is transliterated). "
                      "Empty = \"User\", or with net_profile_generate_xuid the Switch nickname (transliterated), else "
                      "\"Player-XXXX\"");

#if REX_PLATFORM_SWITCH
extern "C" void randomGet(void* buf, size_t len);  // libnx: the kernel's CSPRNG
// sdk/src/core/account_switch.cpp: the account the game runs under.
extern "C" bool RexSwitchAccountIdentity(uint8_t uid_out[16], char* nickname_out, size_t nickname_size, char* why,
                                         size_t why_size);
#endif

namespace {

constexpr uint64_t kDefaultXuid = 0xB13EBABEBABEBABE;
// The default XUID's top 16 bits: 58410A1F refuses XUIDs with any of 0x00C0000000000000 set, and these are clear.
constexpr uint64_t kGeneratedPrefix = 0xB13E000000000000;
constexpr const char* kIdentityFile = "profile_identity.txt";

uint64_t RandomLow48() {
  uint64_t value = 0;
#if REX_PLATFORM_SWITCH
  randomGet(&value, sizeof(value));
#else
  std::random_device device;
  value = (uint64_t(device()) << 32) ^ device();
#endif
  return value & 0x0000FFFFFFFFFFFF;
}

// "xuid=B13E..." from the identity file; 0 if it is missing or not a valid generated XUID.
uint64_t ReadIdentity(const std::filesystem::path& path) {
  std::ifstream file(path);
  std::string line;
  while (std::getline(file, line)) {
    if (line.rfind("xuid=", 0) != 0) continue;
    try {
      const uint64_t xuid = std::stoull(line.substr(5), nullptr, 16);
      if ((xuid & 0xFFFF000000000000) == kGeneratedPrefix && xuid != kDefaultXuid) return xuid;
    } catch (...) {
    }
  }
  return 0;
}

#if REX_PLATFORM_SWITCH
// A stable XUID for an account id: kGeneratedPrefix plus 48 bits of a salted hash, so the id is not exposed.
uint64_t XuidFromAccount(const uint8_t (&uid)[16]) {
  uint64_t hash = 0xCBF29CE484222325;  // FNV-1a over a project salt and the 16 id bytes
  auto add = [&hash](uint8_t byte) {
    hash ^= byte;
    hash *= 0x100000001B3;
  };
  for (const char c : std::string_view("ds2scholar-nx/xuid/v1")) add(uint8_t(c));
  for (const uint8_t byte : uid) add(byte);
  hash ^= hash >> 33;  // splitmix64 finalizer: spread the bits before keeping 48 of them
  hash *= 0xFF51AFD7ED558CCD;
  hash ^= hash >> 33;
  uint64_t xuid = kGeneratedPrefix | (hash & 0x0000FFFFFFFFFFFF);
  if (xuid == kDefaultXuid || (xuid & 0x0000FFFFFFFFFFFF) == 0) xuid ^= 1;
  return xuid;
}
#endif

// Recursive copy for the one-time save migration, with C stdio: on the Switch (newlib) std::filesystem::copy failed
// and file_size of a file just written did too (ds2_148, ds2_149). Directories are created; every file is copied
// and its byte count checked. Failure names the path and errno.
bool CopySaveFile(const std::filesystem::path& from, const std::filesystem::path& to, std::string& failure) {
  FILE* in = std::fopen(from.string().c_str(), "rb");
  if (!in) {
    failure = fmt::format("open {}: errno {}", from.string(), errno);
    return false;
  }
  FILE* out = std::fopen(to.string().c_str(), "wb");
  if (!out) {
    failure = fmt::format("create {}: errno {}", to.string(), errno);
    std::fclose(in);
    return false;
  }
  std::vector<char> buffer(64 * 1024);
  bool ok = true;
  for (;;) {
    const size_t got = std::fread(buffer.data(), 1, buffer.size(), in);
    if (got && std::fwrite(buffer.data(), 1, got, out) != got) {
      failure = fmt::format("write {}: errno {}", to.string(), errno);
      ok = false;
      break;
    }
    if (got < buffer.size()) {
      if (std::ferror(in)) {
        failure = fmt::format("read {}: errno {}", from.string(), errno);
        ok = false;
      }
      break;
    }
  }
  std::fclose(in);
  if (std::fclose(out) != 0 && ok) {
    failure = fmt::format("close {}: errno {}", to.string(), errno);
    ok = false;
  }
  return ok;
}

bool CopyTree(const std::filesystem::path& from, const std::filesystem::path& to, std::string& failure) {
  std::error_code error;
  std::filesystem::create_directories(to, error);
  if (error) {
    failure = to.string() + ": " + error.message();
    return false;
  }
  for (std::filesystem::directory_iterator it(from, error), end; !error && it != end; it.increment(error)) {
    const auto target = to / it->path().filename();
    const bool directory = it->is_directory(error);
    if (error) break;
    if (directory ? !CopyTree(it->path(), target, failure) : !CopySaveFile(it->path(), target, failure)) return false;
  }
  if (error) {
    failure = from.string() + ": " + error.message();
    return false;
  }
  return true;
}

// Gamertag rules of the 360 (15 characters); anything else is dropped.
std::string CleanName(const std::string& name) {
  std::string clean;
  for (char c : name) {
    if (clean.size() == 15) break;
    if (std::isalnum(static_cast<unsigned char>(c)) || c == ' ' || c == '_' || c == '-' || c == '.') {
      clean.push_back(c);
    }
  }
  while (!clean.empty() && clean.back() == ' ') clean.pop_back();
  while (!clean.empty() && clean.front() == ' ') clean.erase(clean.begin());
  return clean;
}

}  // namespace

namespace rex {
namespace system {
namespace xam {

void UserProfile::ResolveIdentity(const std::filesystem::path& content_root) {
  const bool generate = REXCVAR_GET(net_profile_generate_xuid);
  std::string account_nickname;
  if (generate && !REXCVAR_GET(net_profile_xuid) && !content_root.empty()) {
    std::error_code error;
    std::filesystem::create_directories(content_root, error);
    const auto identity = content_root / kIdentityFile;
    uint64_t xuid = 0;
#if REX_PLATFORM_SWITCH
    uint8_t uid[16] = {};
    char nickname[0x21] = {};
    char why[160] = {};
    if (RexSwitchAccountIdentity(uid, nickname, sizeof(nickname), why, sizeof(why))) {
      xuid = XuidFromAccount(uid);
      account_nickname = nickname;
      REXLOG_INFO("[profile] XUID {:016X} from the Switch user account ({})", xuid, why);
    } else {
      REXLOG_WARN("[profile] no Switch user account ({}); the XUID comes from {}", why, identity.string());
    }
#endif
    if (!xuid) xuid = ReadIdentity(identity);
    if (!xuid) {
      do {
        xuid = kGeneratedPrefix | RandomLow48();
      } while (xuid == kDefaultXuid || (xuid & 0x0000FFFFFFFFFFFF) == 0);
      std::ofstream file(identity, std::ios::trunc);
      file << "# ds2scholar-nx: this device's online identity. Deleting it creates a new player.\n"
           << fmt::format("xuid={:016X}\n", xuid);
      if (!file.flush()) {
        REXLOG_ERROR("[profile] cannot write {}; keeping the default XUID", identity.string());
        xuid = 0;
      } else {
        REXLOG_INFO("[profile] new device XUID {:016X} written to {}", xuid, identity.string());
      }
    }
    if (xuid) {
      // The saves live in content_root/<XUID>/...: the default XUID's are copied once (the original stays).
      const auto old_saves = content_root / fmt::format("{:016X}", kDefaultXuid);
      const auto new_saves = content_root / fmt::format("{:016X}", xuid);
      bool usable = true;
      if (!std::filesystem::exists(new_saves) && std::filesystem::exists(old_saves)) {
        const auto partial = content_root / fmt::format("{:016X}.copying", xuid);
        std::filesystem::remove_all(partial, error);
        error.clear();
        std::string failure;
        if (CopyTree(old_saves, partial, failure)) {
          std::filesystem::rename(partial, new_saves, error);
          if (error) failure = "rename " + partial.string() + ": " + error.message();
        }
        if (!failure.empty()) {
          REXLOG_ERROR("[profile] copying the saves {} -> {} failed ({}); this run keeps the default XUID",
                       old_saves.string(), new_saves.string(), failure);
          std::filesystem::remove_all(partial, error);
          usable = false;
        } else {
          REXLOG_INFO("[profile] saves of {:016X} copied to {:016X} (the original folder is kept)", kDefaultXuid,
                      xuid);
        }
      }
      if (usable) xuid_ = xuid;
    }
  }
  std::string name = gamertag::FromNickname(REXCVAR_GET(net_profile_name));
  if (name.empty()) name = CleanName(REXCVAR_GET(net_profile_name));
  if (!name.empty()) {
    name_ = name;
  } else if (generate && xuid_ != kDefaultXuid) {
    // The Switch nickname as a gamertag: as it is, or with Cyrillic transliterated (Даниил -> Daniil); Player-XXXX
    // when it has characters with no Latin form.
    const std::string nickname = gamertag::FromNickname(account_nickname);
    name_ = !nickname.empty() ? nickname : fmt::format("Player-{:04X}", uint32_t(xuid_ & 0xFFFF));
  }
  REXLOG_INFO("[profile] identity: XUID={:016X}, name={}", xuid_, name_);
}

UserProfile::UserProfile() {
  // 58410A1F checks the user XUID against a mask of 0x00C0000000000000 (3<<54),
  // if non-zero, it prevents the user from playing the game.
  // "You do not have permissions to perform this operation."
  xuid_ = 0xB13EBABEBABEBABE;
  name_ = "User";
  if (const auto override_xuid = REXCVAR_GET(net_profile_xuid)) {
    xuid_ = override_xuid;
  }
  REXLOG_INFO("[profile] XUID={:016X}, name={}", xuid_, name_);

  // https://cs.rin.ru/forum/viewtopic.php?f=38&t=60668&hilit=gfwl+live&start=195
  // https://github.com/arkem/py360/blob/master/py360/constants.py
  // XPROFILE_GAMER_YAXIS_INVERSION
  AddSetting(std::make_unique<Int32Setting>(0x10040002, 0));
  // XPROFILE_OPTION_CONTROLLER_VIBRATION
  AddSetting(std::make_unique<Int32Setting>(0x10040003, 3));
  // XPROFILE_GAMERCARD_ZONE
  AddSetting(std::make_unique<Int32Setting>(0x10040004, 0));
  // XPROFILE_GAMERCARD_REGION
  AddSetting(std::make_unique<Int32Setting>(0x10040005, 0));
  // XPROFILE_GAMERCARD_CRED
  AddSetting(std::make_unique<Int32Setting>(0x10040006, 0xFA));
  // XPROFILE_GAMERCARD_REP
  AddSetting(std::make_unique<FloatSetting>(0x5004000B, 0.0f));
  // XPROFILE_OPTION_VOICE_MUTED
  AddSetting(std::make_unique<Int32Setting>(0x1004000C, 0));
  // XPROFILE_OPTION_VOICE_THRU_SPEAKERS
  AddSetting(std::make_unique<Int32Setting>(0x1004000D, 0));
  // XPROFILE_OPTION_VOICE_VOLUME
  AddSetting(std::make_unique<Int32Setting>(0x1004000E, 0x64));
  // XPROFILE_GAMERCARD_MOTTO
  AddSetting(std::make_unique<UnicodeSetting>(0x402C0011, u""));
  // XPROFILE_GAMERCARD_TITLES_PLAYED
  AddSetting(std::make_unique<Int32Setting>(0x10040012, 1));
  // XPROFILE_GAMERCARD_ACHIEVEMENTS_EARNED
  AddSetting(std::make_unique<Int32Setting>(0x10040013, 0));
  // XPROFILE_GAMER_DIFFICULTY
  AddSetting(std::make_unique<Int32Setting>(0x10040015, 0));
  // XPROFILE_GAMER_CONTROL_SENSITIVITY
  AddSetting(std::make_unique<Int32Setting>(0x10040018, 0));
  // Preferred color 1
  AddSetting(std::make_unique<Int32Setting>(0x1004001D, 0xFFFF0000u));
  // Preferred color 2
  AddSetting(std::make_unique<Int32Setting>(0x1004001E, 0xFF00FF00u));
  // XPROFILE_GAMER_ACTION_AUTO_AIM
  AddSetting(std::make_unique<Int32Setting>(0x10040022, 1));
  // XPROFILE_GAMER_ACTION_AUTO_CENTER
  AddSetting(std::make_unique<Int32Setting>(0x10040023, 0));
  // XPROFILE_GAMER_ACTION_MOVEMENT_CONTROL
  AddSetting(std::make_unique<Int32Setting>(0x10040024, 0));
  // XPROFILE_GAMER_RACE_TRANSMISSION
  AddSetting(std::make_unique<Int32Setting>(0x10040026, 0));
  // XPROFILE_GAMER_RACE_CAMERA_LOCATION
  AddSetting(std::make_unique<Int32Setting>(0x10040027, 0));
  // XPROFILE_GAMER_RACE_BRAKE_CONTROL
  AddSetting(std::make_unique<Int32Setting>(0x10040028, 0));
  // XPROFILE_GAMER_RACE_ACCELERATOR_CONTROL
  AddSetting(std::make_unique<Int32Setting>(0x10040029, 0));
  // XPROFILE_GAMERCARD_TITLE_CRED_EARNED
  AddSetting(std::make_unique<Int32Setting>(0x10040038, 0));
  // XPROFILE_GAMERCARD_TITLE_ACHIEVEMENTS_EARNED
  AddSetting(std::make_unique<Int32Setting>(0x10040039, 0));

  // If we set this, games will try to get it.
  // XPROFILE_GAMERCARD_PICTURE_KEY
  AddSetting(std::make_unique<UnicodeSetting>(0x4064000F, u"gamercard_picture_key"));

  // XPROFILE_TITLE_SPECIFIC1
  AddSetting(std::make_unique<BinarySetting>(0x63E83FFF));
  // XPROFILE_TITLE_SPECIFIC2
  AddSetting(std::make_unique<BinarySetting>(0x63E83FFE));
  // XPROFILE_TITLE_SPECIFIC3
  AddSetting(std::make_unique<BinarySetting>(0x63E83FFD));
}

void UserProfile::AddSetting(std::unique_ptr<Setting> setting) {
  Setting* previous_setting = setting.get();
  std::swap(settings_[setting->setting_id], previous_setting);

  if (setting->is_set && setting->is_title_specific()) {
    SaveSetting(setting.get());
  }

  if (previous_setting) {
    // replace: swap out the old setting from the owning list
    for (auto vec_it = setting_list_.begin(); vec_it != setting_list_.end(); ++vec_it) {
      if (vec_it->get() == previous_setting) {
        vec_it->swap(setting);
        break;
      }
    }
  } else {
    // new setting: add to the owning list
    setting_list_.push_back(std::move(setting));
  }
}

UserProfile::Setting* UserProfile::GetSetting(uint32_t setting_id) {
  const auto& it = settings_.find(setting_id);
  if (it == settings_.end()) {
    return nullptr;
  }
  UserProfile::Setting* setting = it->second;
  if (setting->is_title_specific()) {
    // If what we have loaded in memory isn't for the title that is running
    // right now, then load it from disk.
    if (kernel_state_->title_id() != setting->loaded_title_id) {
      LoadSetting(setting);
    }
  }
  return setting;
}

void UserProfile::LoadSetting(UserProfile::Setting* setting) {
  if (setting->is_title_specific()) {
    auto content_dir = kernel_state_->content_manager()->ResolveGameUserContentPath();
    auto setting_id = fmt::format("{:08X}", setting->setting_id);
    auto file_path = content_dir / setting_id;
    auto file = rex::filesystem::OpenFile(file_path, "rb");
    if (file) {
      fseek(file, 0, SEEK_END);
      uint32_t input_file_size = static_cast<uint32_t>(ftell(file));
      fseek(file, 0, SEEK_SET);

      std::vector<uint8_t> serialized_data(input_file_size);
      fread(serialized_data.data(), 1, serialized_data.size(), file);
      fclose(file);
      setting->Deserialize(serialized_data);
      setting->loaded_title_id = kernel_state_->title_id();
    }
  } else {
    // Unsupported for now.  Other settings aren't per-game and need to be
    // stored some other way.
    REXSYS_WARN("Attempting to load unsupported profile setting from disk");
  }
}

void UserProfile::SaveSetting(UserProfile::Setting* setting) {
  if (setting->is_title_specific()) {
    auto serialized_setting = setting->Serialize();
    auto content_dir = kernel_state_->content_manager()->ResolveGameUserContentPath();
    std::filesystem::create_directories(content_dir);
    auto setting_id = fmt::format("{:08X}", setting->setting_id);
    auto file_path = content_dir / setting_id;
    auto file = rex::filesystem::OpenFile(file_path, "wb");
    fwrite(serialized_setting.data(), 1, serialized_setting.size(), file);
    fclose(file);
  } else {
    // Unsupported for now.  Other settings aren't per-game and need to be
    // stored some other way.
    REXSYS_WARN("Attempting to save unsupported profile setting to disk");
  }
}

}  // namespace xam
}  // namespace system
}  // namespace rex
