// Gamertag from a Switch nickname (sdk/include/rex/system/xam/gamertag.h).
#include <cassert>
#include <cstdio>
#include <rex/system/xam/gamertag.h>

using rex::system::xam::gamertag::FromNickname;

int main() {
  assert(FromNickname("Даниил") == "Daniil");
  assert(FromNickname("Костя") == "Kostya");
  assert(FromNickname("ЖЕНЯ") == "ZhENYa");  // only the first Latin letter of a capital is capital
  assert(FromNickname("Щука_77") == "Shchuka_77");
  assert(FromNickname("Объём") == "Obem");
  assert(FromNickname("Їжак Ґудзик") == "Yizhak Gudzik");
  assert(FromNickname("Player One") == "Player One");
  assert(FromNickname("  Depp  ") == "Depp");
  assert(FromNickname("Александрвеликий") == "Aleksandrveliki");  // cut to 15 characters
  assert(FromNickname("Даниил!") == "");   // '!' is not a gamertag character
  assert(FromNickname("Ёлка😀") == "");     // emoji has no Latin form
  assert(FromNickname("名前") == "");
  assert(FromNickname("\xD0") == "");        // truncated UTF-8
  assert(FromNickname("") == "" && FromNickname("ъь") == "");
  puts("gamertag: Cyrillic transliteration, ASCII names, trimming, cut and rejection passed");
}
