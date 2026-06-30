"""
監視銘柄リスト管理ツール

使い方:
  python watchlist.py list              # 一覧表示
  python watchlist.py add 6501 日立製作所  # 追加
  python watchlist.py remove 6501       # 削除
  python watchlist.py check 6501        # 銘柄コードが有効か確認

他のスクリプトからは:
  from watchlist import load_watchlist
  stocks = load_watchlist()  # [{"code": "7203", "name": "トヨタ自動車"}, ...]
"""
import sys
import json
from pathlib import Path

WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"


def load_watchlist() -> list[dict]:
    if not WATCHLIST_FILE.exists():
        return []
    return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8")).get("stocks", [])


def save_watchlist(stocks: list[dict]) -> None:
    WATCHLIST_FILE.write_text(
        json.dumps({"stocks": stocks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _fetch_name(code: str) -> str | None:
    """yfinance で銘柄名を自動取得"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{code}.T")
        info = ticker.info
        name = info.get("longName") or info.get("shortName")
        if name:
            # 英語名から日本語名への変換はできないので英語名を返す
            return name
    except Exception:
        pass
    return None


def cmd_list() -> None:
    stocks = load_watchlist()
    if not stocks:
        print("監視銘柄なし")
        return
    print(f"【監視銘柄一覧】 {len(stocks)}銘柄")
    for i, s in enumerate(stocks, 1):
        print(f"  {i:2}. {s['name']}（{s['code']}）")


def cmd_add(code: str, name: str | None) -> None:
    stocks = load_watchlist()

    # 重複チェック
    if any(s["code"] == code for s in stocks):
        print(f"⚠️  {code} はすでに登録されています")
        cmd_list()
        return

    # 名前が未指定の場合はyfinanceから自動取得
    if not name:
        print(f"銘柄名を取得中...")
        name = _fetch_name(code)
        if not name:
            print(f"⚠️  銘柄名を自動取得できませんでした。手動で入力してください:")
            print(f"  python watchlist.py add {code} <銘柄名>")
            return

    stocks.append({"code": code, "name": name})
    save_watchlist(stocks)
    print(f"✅ 追加: {name}（{code}）")
    print(f"   現在 {len(stocks)} 銘柄を監視中")


def cmd_remove(code: str) -> None:
    stocks = load_watchlist()
    before = len(stocks)
    removed = [s for s in stocks if s["code"] == code]
    stocks = [s for s in stocks if s["code"] != code]

    if len(stocks) == before:
        print(f"⚠️  {code} は監視リストにありません")
        return

    save_watchlist(stocks)
    name = removed[0]["name"] if removed else code
    print(f"✅ 削除: {name}（{code}）")
    print(f"   現在 {len(stocks)} 銘柄を監視中")


def cmd_check(code: str) -> None:
    """銘柄コードが有効かチェック"""
    print(f"コード {code} を確認中...")
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{code}.T")
        info = ticker.info
        name = info.get("longName") or info.get("shortName") or "不明"
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price:
            print(f"✅ 有効: {name}（{code}）  現在値: {price:,.0f}円")
            print(f"  追加する場合: python watchlist.py add {code} {name}")
        else:
            print(f"⚠️  データなし。コードが正しいか確認してください（東証コード4桁）")
    except Exception as e:
        print(f"❌ エラー: {e}")


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] == "list":
        cmd_list()
        return

    if args[0] == "add":
        if len(args) < 2:
            print("使い方: python watchlist.py add <コード> [銘柄名]")
            print("例: python watchlist.py add 6501 日立製作所")
            return
        code = args[1]
        name = " ".join(args[2:]) if len(args) > 2 else None
        cmd_add(code, name)
        return

    if args[0] == "remove":
        if len(args) < 2:
            print("使い方: python watchlist.py remove <コード>")
            return
        cmd_remove(args[1])
        return

    if args[0] == "check":
        if len(args) < 2:
            print("使い方: python watchlist.py check <コード>")
            return
        cmd_check(args[1])
        return

    print("使い方:")
    print("  python watchlist.py list")
    print("  python watchlist.py add <コード> [銘柄名]")
    print("  python watchlist.py remove <コード>")
    print("  python watchlist.py check <コード>")


if __name__ == "__main__":
    main()
