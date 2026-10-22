; Inno Setup script for openhamshack-nb-<version>-setup.exe. Run by
; tools/build-windows.ps1, which passes:
;   /DAppVersion=<ohsnb/VERSION>  /DDistDir=<PyInstaller's dist\openhamshack-nb>
;   /DIconFile=<openhamshack-nb.ico>  /DRepo=<repository root>
;   /DPlutoDrivers=<ADI's PlutoSDR-M2k-USB-Drivers.exe> (pluto-drivers.iss)
;
; Installs per user by default (PrivilegesRequired=lowest): no UAC prompt,
; into %LOCALAPPDATA%\Programs\OpenHamShack QO-100 NB, which is enough for a program
; that writes nothing outside the operator's own profile. The wizard (or
; /ALLUSERS on the command line) still offers Program Files for a shared
; machine. The one machine-wide thing a Pluto needs, ADI's USB drivers, is
; an option that asks for administrator rights for itself alone
; (pluto-drivers.iss). libiio 0.26 is inside the bundle (_internal\libiio),
; so ADI's libiio installer is not needed at all.
;
; Uninstalling removes the program and its shortcuts but leaves
; %APPDATA%\openhamshack-nb - the operator's settings, log and txCorr - as the
; .deb leaves ~/.config: reinstalling must not cost them their station.

#ifndef AppVersion
  #error Pass /DAppVersion=<version> (tools/build-windows.ps1 does)
#endif

[Setup]
; Never change AppId: it is how a newer installer finds the old install to
; upgrade in place, and how Windows matches the uninstaller.
AppId={{5B0E6A3C-6F0B-4C41-9C1E-4A3B7E0C2D91}
AppName=OpenHamShack QO-100 NB
AppVersion={#AppVersion}
AppVerName=OpenHamShack QO-100 NB {#AppVersion}
AppPublisher=360 Technology
AppPublisherURL=https://openhamshack.com/desktop/nb/
AppComments=QO-100 narrowband transceiver
DefaultDirName={autopf}\OpenHamShack QO-100 NB
DefaultGroupName=OpenHamShack QO-100 NB
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=openhamshack-nb-{#AppVersion}-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\openhamshack-nb.exe
UninstallDisplayName=OpenHamShack QO-100 NB {#AppVersion}
LicenseFile={#Repo}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Close a running copy before replacing its files, rather than leaving a
; half-updated folder behind a locked DLL.
CloseApplications=yes
#ifdef Sign
; Signed as 360 Technology: build-windows.ps1 defines Sign and the "ohssign"
; tool (packaging\windows\sign.ps1) unless run with -NoSign. Inno Setup
; then signs the uninstaller before packing it - so Windows names a
; publisher when it is run from Apps, as for setup.exe - and setup.exe
; itself once it is written. The program's own .exes arrive in DistDir
; already signed.
SignTool=ohssign
SignedUninstaller=yes
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; An upgrade replaces the whole bundle: a DLL a newer PyInstaller no longer
; ships must not linger and be picked up instead of the new one.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\OpenHamShack QO-100 NB"; Filename: "{app}\openhamshack-nb.exe"; Comment: "QO-100 narrowband transceiver"
Name: "{group}\OpenHamShack QO-100 NB (console)"; Filename: "{app}\openhamshack-nb-console.exe"; Comment: "The same program with a console, for diagnosing start-up problems"
Name: "{group}\Uninstall OpenHamShack QO-100 NB"; Filename: "{uninstallexe}"
Name: "{autodesktop}\OpenHamShack QO-100 NB"; Filename: "{app}\openhamshack-nb.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\openhamshack-nb.exe"; Description: "{cm:LaunchProgram,OpenHamShack QO-100 NB}"; Flags: nowait postinstall skipifsilent

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
#define AppExe "openhamshack-nb.exe"
#include "pluto-drivers.iss"
#include "self-update.iss"
