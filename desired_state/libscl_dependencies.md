# libscl ビルド依存の記録

dst サーバ（Rocky Linux 8, keisan）で `libscl` をビルドするために導入した
OSS パッケージと外部ライブラリのバージョンを記録する。ここは環境固有値を
含まないため Git 管理対象とする（機密は含めない）。

## OSS（dnf 導入）

| パッケージ | バージョン | 提供物 | 導入経緯 |
| ---------- | ---------- | ------ | -------- |
| libXt-devel | 1.1.5-12.el8 | `X11/Intrinsic.h` | com_prot.h が要求。src(RHEL8.5)と同一バージョン |
| libcurl-devel | 7.61.1-34.el8_10.13 | `curl/curl.h` | scl_webapi_curl.c が要求。dst の libcurl 本体も同版へ更新 |

- 導入元リポジトリ: appstream / baseos（Rocky Linux 8 公式ミラー dl.rockylinux.org）
- 備考: ミラー到達が不安定で `Curl error (28) Timeout` を繰り返すことがある。
  失敗しても時間をおいて再実行すると取得できる。

### libXt-devel が連れてくる依存（参考）
libICE-devel / libSM-devel / libX11-devel / libX11-xcb / libXau-devel /
libxcb-devel / xorg-x11-proto-devel（いずれも el8 系）

## 外部ライブラリ（ソース配置）

| ライブラリ | バージョン | 配置先(dst) | 入手元 |
| ---------- | ---------- | ----------- | ------ |
| nlohmann/json | 3.11.3 | `neo_app/third_party/nlohmann-json-3.11.3/include/nlohmann/json.hpp` | GitHub release v3.11.3 の single-include json.hpp |

- 入手元URL: https://github.com/nlohmann/json/releases/download/v3.11.3/json.hpp
- 単一ヘッダ（ヘッダオンリー）。Makefile の `-I .../third_party/nlohmann-json-3.11.3/include` で参照。

## src から配置した社内ヘッダ（参考・機密ではない構造情報）

- `/usr/include/mcl` 配下のリンク先 `BLenDer-ANM-Code-c/usr/include/mcl`（FILE/opf/kcl 等）
- `BLenDer-ANM-Code-c/anm/cmn/include`（Cmn0010Const.h 等の cmn ヘッダ群）
- opf ヘッダはポインタ版（`/home/cal/include/libOPFVeriTool.h` 相当）で運用する方針。
