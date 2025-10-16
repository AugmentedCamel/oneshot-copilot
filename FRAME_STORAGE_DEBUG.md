# Frame Storage Debugging

This feature allows you to save all ingested frames to disk for debugging and verification purposes, helping you ensure frames are not being reused.

## How to Enable

Add the following to your `.env` file:

```env
SAVE_FRAMES_TO_DISK=True
```

## Where Frames Are Saved

Frames are saved to: `app/data/frames/`

Each frame is saved with its `frame_id` as the filename, for example:
- `app/data/frames/frame_12345.jpg`
- `app/data/frames/frame_12346.jpg`

## Verifying Unique Frames

Once enabled, you can:

1. **Visually Compare**: Open the saved frames in the `app/data/frames/` directory and visually compare them to ensure they're different.

2. **Check File Hashes**: Use a hash comparison tool to verify frames are unique:
   ```bash
   # On Windows (PowerShell)
   Get-ChildItem app\data\frames\*.jpg | Get-FileHash | Format-Table Hash, Path

   # On Linux/Mac
   md5sum app/data/frames/*.jpg
   ```

3. **Check Metadata**: Each frame has a unique `frame_id` in the filename, making it easy to track which frame was processed when.

## Performance Impact

**Note**: Saving frames to disk adds I/O overhead. This feature is intended for debugging only and should be disabled in production.

- Typical overhead: 5-20ms per frame depending on disk speed
- Storage: Each frame is ~50-200KB depending on image quality

## Disabling

To disable frame storage, either:
1. Remove `SAVE_FRAMES_TO_DISK` from your `.env` file
2. Set it to `False`: `SAVE_FRAMES_TO_DISK=False`

## Cleaning Up

To remove saved frames:

```bash
# Windows
del app\data\frames\*.jpg

# Linux/Mac
rm app/data/frames/*.jpg
```

## Log Output

When enabled, you'll see log messages like:
```
[FRAME_STORE] Frame saved to disk - path=app/data/frames/frame_12345.jpg