/**
 * ds2scholar-nx: the Switch user account behind the online identity (docs/online-public-plan.md, stage A).
 *
 * RexSwitchAccountIdentity gives the user id and nickname of the account the game runs under: the preselected user
 * (an application launch with user selection), else the system's user selector (with one user it picks that user
 * without showing anything), else the only user of the console, else the last opened one.
 * UserProfile hashes the id into the XUID, so the identity survives a new NRO, a deleted profile file or another SD
 * card, and every user of the console gets its own. The id itself never leaves the console. `why` tells, for the log,
 * which source gave the user or the result codes of every attempt.
 */

#include <rex/platform.h>

#if REX_PLATFORM_SWITCH

#include <switch.h>

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>

extern "C" bool RexSwitchAccountIdentity(uint8_t uid_out[16], char* nickname_out, size_t nickname_size, char* why,
                                         size_t why_size) {
  if (!uid_out || !nickname_out || nickname_size == 0 || !why || why_size == 0) {
    return false;
  }
  nickname_out[0] = '\0';
  why[0] = '\0';
  const Result init = accountInitialize(AccountServiceType_Application);
  if (R_FAILED(init)) {
    std::snprintf(why, why_size, "accountInitialize 0x%X", unsigned(init));
    return false;
  }
  AccountUid uid{};
  const char* source = nullptr;
  const Result preselected = accountGetPreselectedUser(&uid);
  if (R_SUCCEEDED(preselected) && accountUidIsValid(&uid)) {
    source = "preselected user";
  }
  Result selector = 0;
  if (!source) {
    // Several users: the player picks one, as in a retail game. is_skip_enabled selects a single user silently.
    PselUserSelectionSettings settings{};
    settings.is_skip_enabled = 1;
    selector = pselShowUserSelector(&uid, &settings);
    if (R_SUCCEEDED(selector) && accountUidIsValid(&uid)) source = "user selector";
  }
  Result list = 0;
  s32 total = 0;
  if (!source) {
    AccountUid users[ACC_USER_LIST_SIZE] = {};
    list = accountListAllUsers(users, ACC_USER_LIST_SIZE, &total);
    if (R_SUCCEEDED(list) && total == 1 && accountUidIsValid(&users[0])) {
      uid = users[0];
      source = "the only user of the console";
    }
  }
  Result last = 0;
  if (!source) {
    last = accountGetLastOpenedUser(&uid);
    if (R_SUCCEEDED(last) && accountUidIsValid(&uid)) source = "last opened user";
  }
  if (source) {
    std::memcpy(uid_out, &uid, 16);
    std::snprintf(why, why_size, "%s", source);
    AccountProfile profile{};
    if (R_SUCCEEDED(accountGetProfile(&profile, uid))) {
      AccountProfileBase base{};
      if (R_SUCCEEDED(accountProfileGet(&profile, nullptr, &base))) {
        const size_t length = strnlen(base.nickname, sizeof(base.nickname));
        const size_t copied = length < nickname_size - 1 ? length : nickname_size - 1;
        std::memcpy(nickname_out, base.nickname, copied);
        nickname_out[copied] = '\0';
      }
      accountProfileClose(&profile);
    }
  } else {
    std::snprintf(why, why_size, "preselected 0x%X, selector 0x%X, user list 0x%X with %d user(s), last opened 0x%X",
                  unsigned(preselected), unsigned(selector), unsigned(list), int(total), unsigned(last));
  }
  accountExit();
  return source != nullptr;
}

#endif  // REX_PLATFORM_SWITCH
