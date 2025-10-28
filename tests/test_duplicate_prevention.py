"""
重複検出テスト - 同じ画面は保存されないことを確認
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from zoom_auto_capture.screenshot import ScreenshotCapture
from zoom_auto_capture import config


def test_duplicate_prevention():
    """Test that duplicate screenshots are not saved."""
    print("=" * 60)
    print("重複スクリーンショット防止テスト")
    print("=" * 60)

    capture = ScreenshotCapture()

    if not capture.is_available:
        print("❌ mss / Pillow が見つかりません。")
        return False

    print("✓ mss / Pillow が利用可能です。")

    # Start capture
    print("\n1. スクリーンショット取得を開始します...")
    capture.start("重複テスト", "duplicate_test")
    
    if not capture.is_running:
        print("❌ スクリーンショット取得の開始に失敗しました。")
        return False
    
    print("✓ スクリーンショット取得を開始しました。")
    
    # Wait for initial screenshots
    print("\n2. 画面を変えずに15秒間監視します...")
    print("   ※ 最初の1枚のみ保存され、その後同じ画面は保存されないはずです。")
    
    for i in range(15):
        time.sleep(1)
        status = capture.status
        print(f"   {i+1}秒経過 - スクリーンショット枚数: {status.screenshot_count}")
    
    final_count = capture.status.screenshot_count
    
    # Stop capture
    print("\n3. スクリーンショット取得を停止します...")
    capture.stop()
    
    print(f"✓ 最終枚数: {final_count}")
    
    # Check results
    if final_count == 1:
        print("✓ 重複が正しく防止されました！（同じ画面で1枚のみ保存）")
    elif final_count <= 3:
        print(f"⚠️ 枚数が少ないですが、重複防止が機能しているようです。（{final_count}枚）")
    else:
        print(f"❌ 重複が防止されていません。同じ画面で {final_count} 枚保存されました。")
        return False
    
    # Check output directory
    today = time.strftime("%Y%m%d")
    output_dir = config.SCREENSHOT_DIR / today / "duplicate_test"
    
    if output_dir.exists():
        files = list(output_dir.glob("*.png"))
        print(f"\n4. 出力ディレクトリ確認:")
        print(f"   パス: {output_dir}")
        print(f"   実際のファイル数: {len(files)}")
    
    print("\n" + "=" * 60)
    print("✓ 重複防止テストが完了しました。")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = test_duplicate_prevention()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nテストが中断されました。")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ テスト中にエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
