; Inno Setup script for openhamshack-radio-<version>-setup.exe: openhamshack-nb.iss's
; twin, run by tools/build-windows.ps1 -App ham with the same /D values
; (AppVersion from ohsradio/VERSION, DistDir PyInstaller's dist\openhamshack-radio,
; IconFile openhamshack-radio.ico). Read openhamshack-nb.iss for why it installs per
; user, closes a running copy and replaces _internal whole.
;
; Side by side with QO-100 NB: its own AppId, folder, Start-menu entries
; and uninstaller, and its own %APPDATA%\openhamshack-radio for settings, so
; installing, upgrading or removing either never touches the other.
;
; Uninstalling leaves %APPDATA%\openhamshack-radio - settings, log, band stacks
; and power chain - as the .deb leaves ~/.config/openhamshack-radio.

#ifndef AppVersion
  #error Pass /DAppVersion=<version> (tools/build-windows.ps1 does)
#endif

[Setup]
; Never change AppId: it is how a newer installer finds the old install to
; upgrade in place, and how Windows matches the uninstaller. It must also
; never equal QO-100 NB's, or one would upgrade "over" the other.
AppId={{6CB153AC-60F0-4FF0-8805-E27009992212}
AppName=OpenHamShack Radio
AppVersion={#AppVersion}
AppVerName=OpenHamShack Radio {#AppVersion}
AppPublisher=360 Technology
AppPublisherURL=https://openhamshack.com/desktop/ham/
AppComments=All-bands amateur radio SDR transceiver
DefaultDirName={autopf}\OpenHamShack Radio
DefaultGroupName=OpenHamShack Radio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=openhamshack-radio-{#AppVersion}-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\openhamshack-radio.exe
UninstallDisplayName=OpenHamShack Radio {#AppVersion}
LicenseFile={#Repo}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
#ifdef Sign
; Signed as 360 Technology, as openhamshack-nb.iss says.
SignTool=ohssign
SignedUninstaller=yes
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\OpenHamShack Radio"; Filename: "{app}\openhamshack-radio.exe"; Comment: "All-bands amateur radio SDR transceiver"
Name: "{group}\OpenHamShack Radio (console)"; Filename: "{app}\openhamshack-radio-console.exe"; Comment: "The same program with a console, for diagnosing start-up problems"
Name: "{group}\Uninstall OpenHamShack Radio"; Filename: "{uninstallexe}"
Name: "{autodesktop}\OpenHamShack Radio"; Filename: "{app}\openhamshack-radio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\openhamshack-radio.exe"; Description: "{cm:LaunchProgram,OpenHamShack Radio}"; Flags: nowait postinstall skipifsilent

; The PlutoSDR USB drivers option: [Tasks], [Files] and [Code] of its own,
; shared with the other app's installer. Read it for how it elevates and
; how it knows the drivers are already there.
;
; Starting the program again after it updated itself (ohscore/update.py runs
; this installer unattended, with /RELAUNCH=1). Read it for the switches.
;
; The includes stay last and back to back, with every ";" comment
; above them: #include pastes text, so a comment line after the first one
; would land inside pluto-drivers.iss's [Code] section, where ";" is
; Pascal's statement separator, not a comment, and ISCC stops with
; "'BEGIN' expected" (the first build of 0.1.9 did).
#define AppExe "openhamshack-radio.exe"
#include "pluto-drivers.iss"
#include "self-update.iss"
