# Local Firmware Directory

Place your downloaded HPE iLO firmware packages in this folder.

## Supported Formats
- **`.fwpkg`** (Recommended for iLO 5 & iLO 6): HPE signed component package format.
- **`.bin`** (Supported for iLO 4, iLO 5, iLO 6): Raw binary flash image.
- **`.compsig`** (Component Signature): If your component came with a separate `.compsig` signature file, keep it alongside the firmware file with the same base name (e.g. `ilo5_304.fwpkg` and `ilo5_304.compsig`).

## Where to Download Official HPE iLO Firmware
1. Visit the **HPE Support Center**:
   - [HPE Support Center Portal](https://support.hpe.com/)
2. Search for your server generation or management controller:
   - Example: *"iLO 5 for HPE ProLiant Gen10 Servers"*
   - Example: *"iLO 6 for HPE ProLiant Gen11 Servers"*
3. Under **Software Type**, filter by **Firmware - Lights-Out Management**.
4. Download the firmware package (e.g. `ilo5_304.fwpkg` or `ilo6_167.fwpkg`).
5. Copy or move the downloaded file into this `firmware/` directory.

## Automatic Matching
The automation tool automatically detects the target generation from the filename:
- Files containing `ilo5` or `ilo_5` are matched to **iLO 5** servers.
- Files containing `ilo6` or `ilo_6` are matched to **iLO 6** servers.
- Files containing `ilo7` or `ilo_7` are matched to **iLO 7** servers.
- Files containing `ilo4` or `ilo_4` are matched to **iLO 4** servers.
