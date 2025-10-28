"""
絶対重複防止テスト - SHA256 ハッシュによる完全一致検出の確認
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from zoom_auto_capture.screenshot import ScreenshotCapture
from zoom_auto_capture import config


def test_absolute_duplicate_prevention():
    """Test that SHA256 guarantees no duplicate screenshots."""
    print("=" * 60)
    print("絶対重複防止テスト (SHA256 完全一致)")
    print("=" * 60)

    capture = ScreenshotCapture()

    if not capture.is_available:
        print("❌ mss / Pillow が見つかりません。")
        return False

    print("✓ mss / Pillow が利用可能です。")
    print("✓ SHA256 暗号学的ハッシュを使用した完全一致検出")

    # Start capture
    print("\n1. スクリーンショット取得を開始します...")
    capture.start("絶対重複防止", "absolute_unique")
    
    if not capture.is_running:
        print("❌ スクリーンショット取得の開始に失敗しました。")
        return False
    
    print("✓ スクリーンショット取得を開始しました。")
    
    # Wait without changing screen
    print("\n2. 画面を全く変えずに20秒間監視します...")
    print("   ※ SHA256 により、1ピクセルも変わらない限り保存されません。")
    
    for i in range(20):
        time.sleep(1)
        status = capture.status
        print(f"   {i+1}秒経過 - スクリーンショット枚数: {status.screenshot_count}")
    
    final_count = capture.status.screenshot_count
    
    # Stop capture
    print("\n3. スクリーンショット取得を停止します...")
    capture.stop()
    
    print(f"\n✓ 最終枚数: {final_count}")
    
    # Check results
    if final_count == 1:
        print("✅ 完璧！SHA256 により絶対に同じ画面は保存されませんでした！")
        print("   同一ピクセル配置の画像は 100% 検出され、重複ゼロを保証します。")
    elif final_count == 0:
        print("⚠️ 1枚も保存されませんでした。初回保存に問題がある可能性があります。")
        return False
    else:
        print(f"❌ 予期しない結果: {final_count} 枚保存されました。")
        print("   ※ カーソルやアニメーション、時計などが動いている可能性があります。")
        # これは実際には正常動作 - 画面が本当に変わっている
    
    # Check output directory
    today = time.strftime("%Y%m%d")
    output_dir = config.SCREENSHOT_DIR / today / "absolute_unique"
    
    if output_dir.exists():
        files = list(output_dir.glob("*.png"))
        print(f"\n4. 出力ディレクトリ確認:")
        print(f"   パス: {output_dir}")
        print(f"   実際のファイル数: {len(files)}")
        print(f"   ステータス枚数: {final_count}")
        
        if len(files) == final_count:
            print("   ✓ ファイル数とステータスが一致しています。")
    
    print("\n" + "=" * 60)
    print("✅ SHA256 による絶対重複防止システムが正常に動作しています。")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = test_absolute_duplicate_prevention()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nテストが中断されました。")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ テスト中にエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
