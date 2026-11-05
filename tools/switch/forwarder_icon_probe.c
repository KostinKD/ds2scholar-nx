// Read-only inspection of DS2's installed control data and NS cache.
// Does not modify content metadata, icons, saves or application records.
#include <switch.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

u32 __nx_applet_type = AppletType_Application;
static const u64 title_id = 0x01445332534F0000ULL;
static NsApplicationControlData control;
static const char* root = "sdmc:/switch/ds2scholar-nx/forwarder_probe";

static void write_file(const char* name, const void* data, size_t size) {
    char path[256];
    snprintf(path, sizeof(path), "%s/%s", root, name);
    FILE* file = fopen(path, "wb");
    if (file) { fwrite(data, 1, size, file); fclose(file); }
}

static void inspect_control(FILE* report, NsApplicationControlSource source, const char* name) {
    memset(&control, 0, sizeof(control));
    u64 actual = 0;
    Result result = nsGetApplicationControlData(source, title_id, &control, sizeof(control), &actual);
    fprintf(report, "%s result=%08X actual=%llu\n", name, result, (unsigned long long)actual);
    printf("%s: %08X, %llu bytes\n", name, result, (unsigned long long)actual);
    if (R_FAILED(result) || actual < sizeof(NacpStruct) || actual > sizeof(control)) return;
    char path[80];
    snprintf(path, sizeof(path), "%s.nacp", name);
    write_file(path, &control.nacp, sizeof(control.nacp));
    size_t size = actual - sizeof(NacpStruct);
    u8 hash[32];
    sha256CalculateHash(hash, control.icon, size);
    fprintf(report, "%s display_version=%.16s languages=%08X icon_bytes=%zu icon_sha256=",
            name, control.nacp.display_version, control.nacp.supported_language_flag, size);
    for (unsigned i = 0; i < sizeof(hash); ++i) fprintf(report, "%02x", hash[i]);
    fprintf(report, "\n");
    snprintf(path, sizeof(path), "%s.jpg", name);
    if (size) write_file(path, control.icon, size);
    fflush(report);
}

static void inspect_database(FILE* report, NcmStorageId storage) {
    NcmContentMetaDatabase db;
    Result result = ncmOpenContentMetaDatabase(&db, storage);
    fprintf(report, "storage=%u open=%08X\n", storage, result);
    if (R_FAILED(result)) return;
    NcmContentMetaKey key;
    result = ncmContentMetaDatabaseGetLatestContentMetaKey(&db, &key, title_id);
    fprintf(report, "storage=%u latest=%08X", storage, result);
    if (R_SUCCEEDED(result)) {
        fprintf(report, " version=%u type=%02X", key.version, key.type);
        NcmContentId id;
        result = ncmContentMetaDatabaseGetContentIdByType(&db, &id, &key, NcmContentType_Control);
        fprintf(report, " control_result=%08X control_id=", result);
        if (R_SUCCEEDED(result)) for (unsigned i = 0; i < sizeof(id.c); ++i) fprintf(report, "%02x", id.c[i]);
    }
    fprintf(report, "\n");
    serviceClose(&db.s);
}

int main(void) {
    consoleInit(NULL);
    mkdir(root, 0777);
    char path[256];
    snprintf(path, sizeof(path), "%s/report.txt", root);
    FILE* report = fopen(path, "w");
    if (!report) { consoleExit(NULL); return 1; }
    fprintf(report, "DS2 forwarder installed-control probe title=%016llX\n", (unsigned long long)title_id);
    printf("DS2 HOME icon probe (read only)\n\n");
    Result result = nsInitialize();
    fprintf(report, "nsInitialize=%08X\n", result);
    if (R_SUCCEEDED(result)) {
        inspect_control(report, NsApplicationControlSource_CacheOnly, "cache");
        inspect_control(report, NsApplicationControlSource_StorageOnly, "storage");
        nsExit();
    }
    result = ncmInitialize();
    fprintf(report, "ncmInitialize=%08X\n", result);
    if (R_SUCCEEDED(result)) {
        inspect_database(report, NcmStorageId_BuiltInUser);
        inspect_database(report, NcmStorageId_SdCard);
        ncmExit();
    }
    fclose(report);
    printf("\nSaved: /switch/ds2scholar-nx/forwarder_probe\nPress + to exit (or wait 10 seconds).\n");
    PadState pad;
    padConfigureInput(1, HidNpadStyleSet_NpadStandard);
    padInitializeDefault(&pad);
    for (unsigned i = 0; i < 600 && appletMainLoop(); ++i) {
        padUpdate(&pad);
        if (padGetButtonsDown(&pad) & HidNpadButton_Plus) break;
        consoleUpdate(NULL);
        svcSleepThread(16666666);
    }
    consoleExit(NULL);
    return 0;
}
