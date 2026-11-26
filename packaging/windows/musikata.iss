; Inno Setup's script for MusiKata-<version>-setup.exe (R1.4, A6.4), built under Wine by
; scripts/build-windows.sh: for the current user by default, with no UAC prompt; /ALLUSERS (or the
; dialog) installs for everyone into Program Files. It registers the file kinds of R1.7 for "Open
; with" only: MusiKata is offered for them, and the default player stays the user's choice.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Windows finds MusiKata's Uninstall entry by this id: it never changes
AppId={{1CDA0F2B-77FC-47BD-9037-B8C7CF62BC1D}
AppName=MusiKata
AppVersion={#AppVersion}
AppVerName=MusiKata {#AppVersion}
AppPublisher=MusiKata
AppPublisherURL=https://github.com/MojoKata/MusiKata
AppComments=Play, tag and organize your music
DefaultDirName={autopf}\MusiKata
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 22H2 and later (R1.1)
MinVersion=10.0.19045
OutputBaseFilename=MusiKata-{#AppVersion}-setup
SetupIconFile=..\..\build\windows\musikata.ico
UninstallDisplayIcon={app}\musikata.exe
UninstallDisplayName=MusiKata
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
ChangesAssociations=yes

[Files]
; the build's folder, with LICENSE.txt and THIRD-PARTY-NOTICES.txt beside musikata.exe (A6.6)
Source: "..\..\build\windows\dist\MusiKata\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[InstallDelete]
; files of an older version that this one doesn't have
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\MusiKata"; Filename: "{app}\musikata.exe"; Comment: "Play, tag and organize your music"; AppUserModelID: "MusiKata.MusiKata"

[Registry]
; HKA: HKCU for the current user, HKLM for everyone. Two kinds of file, each a ProgID with its
; command; each extension names them under OpenWithProgids, and the application lists them as the
; kinds it supports, which is what "Open with" offers, and nothing sets an extension's default.
Root: HKA; Subkey: "Software\Classes\MusiKata.Audio"; ValueType: string; ValueName: ""; ValueData: "Audio file"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\MusiKata.Audio\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\musikata.exe"",0"
Root: HKA; Subkey: "Software\Classes\MusiKata.Audio\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\musikata.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\MusiKata.Playlist"; ValueType: string; ValueName: ""; ValueData: "Playlist"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\MusiKata.Playlist\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\musikata.exe"",0"
Root: HKA; Subkey: "Software\Classes\MusiKata.Playlist\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\musikata.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\musikata.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "MusiKata"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\musikata.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\musikata.exe"" ""%1"""
; the kinds of R2.2, and R8's playlists
Root: HKA; Subkey: "Software\Classes\.mp3\OpenWithProgids"; ValueType: string; ValueName: "MusiKata.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\musikata.exe\SupportedTypes"; ValueType: string; ValueName: ".mp3"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.flac\OpenWithProgids"; ValueType: string; ValueName: "MusiKata.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\musikata.exe\SupportedTypes"; ValueType: string; ValueName: ".flac"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.m4a\OpenWithProgids"; ValueType: string; ValueName: "MusiKata.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\musikata.exe\SupportedTypes"; ValueType: string; ValueName: ".m4a"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.ogg\OpenWithProgids"; ValueType: string; ValueName: "MusiKata.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\musikata.exe\SupportedTypes"; ValueType: string; ValueName: ".ogg"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.opus\OpenWithProgids"; ValueType: string; ValueName: "MusiKata.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\musikata.exe\SupportedTypes"; ValueType: string; ValueName: ".opus"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.wav\OpenWithProgids"; ValueType: string; ValueName: "MusiKata.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\musikata.exe\SupportedTypes"; ValueType: string; ValueName: ".wav"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.aif\OpenWithProgids"; ValueType: string; ValueName: "MusiKata.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\musikata.exe\SupportedTypes"; ValueType: string; ValueName: ".aif"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.aiff\OpenWithProgids"; ValueType: string; ValueName: "MusiKata.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\musikata.exe\SupportedTypes"; ValueType: string; ValueName: ".aiff"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.m3u\OpenWithProgids"; ValueType: string; ValueName: "MusiKata.Playlist"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\musikata.exe\SupportedTypes"; ValueType: string; ValueName: ".m3u"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\.m3u8\OpenWithProgids"; ValueType: string; ValueName: "MusiKata.Playlist"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\musikata.exe\SupportedTypes"; ValueType: string; ValueName: ".m3u8"; ValueData: ""

[Run]
Filename: "{app}\musikata.exe"; Description: "Open MusiKata"; Flags: postinstall nowait skipifsilent runasoriginaluser
