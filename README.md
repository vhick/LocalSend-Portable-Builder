# LocalSend Portable Builder — Windows ZIP only

This ready-to-upload kit builds a **community portable ZIP** from [LocalSend's official Windows ZIP release](https://github.com/localsend/localsend/releases). It does **not** require a fork of LocalSend, does **not** modify the original LocalSend application, and does **not** build a `.paf.exe` installer.

**Status:** 12 offline tests passed. Windows GitHub Actions packaging and actual network/settings behavior remain to be tested.

## What makes it portable?

The upstream LocalSend Windows ZIP contains `settings.json` next to `localsend_app.exe`, which activates LocalSend's native portable mode. The app writes settings directly to that file, as verified in the official v1.18.2 source. This builder creates a launcher that keeps the *persistent* copy inside `Data/Settings/settings.json` rather than `App/LocalSend`.

- **NTFS drive:** Creates a hard link between `App/LocalSend/settings.json` and `Data/Settings/settings.json`. Changes go to the same physical file immediately. Does not need administrator permissions, registry redirection or copy-back. Removes the working link when LocalSend exits cleanly.
- **exFAT/FAT32 drive:** Hard links aren't available. The launcher works with a temporary settings copy, saves it back to Data approximately every second after changes and when the process ends, and validates JSON before overwriting a saved copy. **An abrupt computer crash could lose recent changes.**
- **After a crash:** If two settings files exist but have identical contents, the launcher removes the stale App copy. If their contents differ, it refuses to start rather than silently destroy data. Back up both files for investigation.
- **Flutter's internal `App/LocalSend/data` is not user data.** It contains runtime libraries/assets and must be replaced with `App` on upgrades. Your *persistent* `Data/` directory is distinct from it.

## First-time GitHub setup: easy method

1. Sign in at https://github.com/new . Create a **new empty** repository called `LocalSend-Portable-Builder`. Select **Public** if you wish; never upload personal settings. Do **not** generate a README, license or .gitignore from GitHub (they're supplied in this ZIP).
2. Download this builder ZIP and **Extract All** on Windows. It includes `.github`, `builder`, `tests`, `README.md`, `START-HERE.txt`, and `.gitignore`.
3. In your working **GitHub Desktop**, choose **File > Clone repository** and clone the empty repository above.
4. Click **Repository > Show in Explorer**. Copy the **contents** of the extracted builder kit (not the ZIP file itself) into that cloned repository folder, preserving hidden `.github`.
5. Return to GitHub Desktop. Review **Changes**, enter a message like `Add LocalSend portable builder`, click **Commit to main**, then **Push origin**.
6. Open your builder repository on GitHub.com. Click **Actions > Build LocalSend True Portable ZIP (Manual) > Run workflow**.
7. For a typical Intel/AMD Windows PC use **version `1.18.2`**, **architecture `x64`**. If using Windows on ARM, select **arm64**. Click the final green **Run workflow** button.
8. Wait for a green checkmark. Under **Artifacts**, download `LocalSend-1.18.2-x64-TruePortable` (or selected version/arch). Extract the GitHub artifact ZIP. It contains **`LocalSend-1.18.2-x64-True-Portable.zip`**. Extract that one as well.
9. Open the extracted `LocalSendPortable` directory and **launch `LocalSendPortable.exe`**, not the inner `App/LocalSend/localsend_app.exe`.

**If an Actions build fails:** open the red failed step, choose **Download log archive**, and share the log. Start a *new workflow run* after committing fixes; **Re-run jobs** uses the old code.

## Expected application layout

```text
LocalSendPortable/
  LocalSendPortable.exe         <-- Always launch this
  App/
    LocalSend/
      localsend_app.exe         <-- Original LocalSend Flutter executable
      data/                     <-- Required Flutter runtime assets (NOT saved settings)
      *.dll
      settings.json             <-- Appears only while launcher is running
    AppInfo/
      appinfo.ini               <-- Display name and category for PortableApps Menu
      appicon.ico               <-- Official LocalSend icon, not generated artwork
      appicon_16.png ... appicon_256.png
  Data/
    Settings/
      settings.json             <-- Saved settings created on first launch
    Received Files/             <-- Optional destination; set it inside the app
    Temp/
  Other/
    Source/
      LICENSE.txt
      build-info.txt
```

The official Windows ZIP is downloaded from the upstream GitHub release and verified against its published SHA-256 digest. v1.18.2 additionally requires a pinned checksum (x64: `737aab1829d901e1d798cddd1e5fdc06ba9dfcc9ea50cfe3805e047005d5e71a`). If an official asset lacks a published SHA-256 digest, or the digests disagree, packaging stops.

## First-run validation (on your Windows PC)

1. Open `LocalSendPortable.exe`. Windows Firewall may ask to allow LocalSend on private networks. If device discovery is needed, allow on **Private** networks only after confirming you are on a trusted network.
2. In LocalSend settings, change the device name, theme or other preferences. Exit the app completely using **Quit** from its system tray menu; closing the window may only hide it.
3. Check that `Data/Settings/settings.json` exists and contains your settings. On NTFS, `App/LocalSend/settings.json` should disappear after exit.
4. Restart `LocalSendPortable.exe`. Ensure changes persist. Send and receive a small test file with another device on the same local network.
5. In LocalSend's receive settings, **manually choose** `LocalSendPortable/Data/Received Files` if you want received files retained in the portable directory. The launcher does not silently change this preference.
6. Check `%APPDATA%/LocalSend` and Windows startup settings. Portable mode should prevent LocalSend's ordinary settings path, but the app or Windows may still create other traces. The builder does not create firewall exceptions or autostart entries; **leave LocalSend's startup-at-login option disabled** to avoid a host registry entry.

LocalSend uses **TCP and UDP port 53317** for incoming connections. LocalSend does not require a background server, special kernel driver or administrator permissions. Windows Firewall permission is host-specific and not inherently portable.

## Safe updates and upgrades

1. Quit LocalSend completely (including system tray).
2. Back up the entire `Data` directory, especially `Data/Settings/settings.json` and received files.
3. Run the GitHub builder with a newer **existing official stable version**. This ZIP builder checks GitHub's release asset digest, and stops on missing/mismatched digests.
4. Download and extract the new finished portable ZIP into a separate temporary location.
5. In your old `LocalSendPortable` folder, replace **`App`** and **`LocalSendPortable.exe`**, not `Data`. You can also replace `Other` if desired. Do not merge new `Data` into existing user data.
6. Run the launcher and verify settings are present. If you move the portable folder to a different drive, update any absolute destination paths saved in LocalSend.

**Never** delete the old `Data` folder to update LocalSend. Never update `App` while LocalSend is running. Avoid launching `App/LocalSend/localsend_app.exe` directly because it bypasses the settings linking and cleanup logic.

## Security, privacy, and support boundaries

- This is an **unofficial community repackaging**, not a LocalSend release or PortableApps.com-supported application/installer.
- The ZIP is only a builder kit; the official app is downloaded by your own GitHub Actions job, not contained here.
- The application ZIP includes no actual user settings or user files; a new `Data/Settings/settings.json` is created on first run.
- Never commit your personal `Data` directory or private received files to the builder repository.
- Some Windows traces and per-machine firewall permissions may remain. Full remnant-free behavior is **not** guaranteed.
- A Windows hard link is a filesystem feature that requires support from the underlying disk, typically NTFS. On exFAT/FAT32, the timed-copy fallback is less resilient to crashes.
- GitHub Actions is manual (`workflow_dispatch`) and does not automatically synchronize/build newer releases.

## Primary sources

- LocalSend project: https://github.com/localsend/localsend
- Tagged source `v1.18.2`: https://github.com/localsend/localsend/tree/v1.18.2
- Official portable mode: https://github.com/localsend/localsend#portable-mode
- Direct settings writes: https://github.com/localsend/localsend/blob/v1.18.2/app/lib/util/shared_preferences/shared_preferences_file.dart
- Official Windows icon: https://github.com/localsend/localsend/blob/v1.18.2/app/windows/runner/resources/app_icon.ico
- PortableApps.com Format 3.9: https://portableapps.com/development/portableapps.com_format
