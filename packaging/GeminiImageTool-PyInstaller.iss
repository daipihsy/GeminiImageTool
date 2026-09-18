; CI installer for the PyInstaller onedir Windows build.

#ifndef StageDir
  #error StageDir must point to dist\GeminiImageTool
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#ifndef IconFile
  #define IconFile "..\assets\GeminiImageTool.ico"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "2.3.0-beta.1"
#endif

#define MyAppName "GeminiImageTool"
#define MyAppExeName "GeminiImageTool.exe"

[Setup]
AppId={{37080BAB-16D8-4775-8186-3D286DB65C20}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SourceDir={#StageDir}
OutputDir={#OutputDir}
OutputBaseFilename=GeminiImageTool-Windows-Setup-v{#MyAppVersion}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式 / Create a desktop shortcut"; GroupDescription: "附加图标 / Additional icons:"

[Files]
Source: "*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
; 桌面快捷方式改由脚本末尾的 Pascal 代码创建：桌面被重定向到 OneDrive、网络位置或加密盘时，
; IPersistFile::Save 会报 0x800701C0（不受信任的装入点），写在这一节里会直接中断安装。
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName} / Launch now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{autodesktop}\{#MyAppName}.lnk"
Type: filesandordirs; Name: "{app}\runtime\pycache"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
// 创建桌面快捷方式；失败不中断安装，程序仍可从开始菜单启动。
procedure CreateDesktopShortcutSafely;
var
  CreatedPath: String;
begin
  try
    CreatedPath := CreateShellLink(
      ExpandConstant('{autodesktop}\{#MyAppName}.lnk'),
      '{#MyAppName}',
      ExpandConstant('{app}\{#MyAppExeName}'),
      '',
      ExpandConstant('{app}'),
      ExpandConstant('{app}\{#MyAppExeName}'),
      0,
      SW_SHOWNORMAL);
    Log('Desktop shortcut created: ' + CreatedPath);
  except
    Log('Desktop shortcut failed: ' + GetExceptionMessage);
    MsgBox('桌面快捷方式创建失败（桌面可能位于 OneDrive、网络位置或加密盘）。' + #13#10 +
           '安装已正常完成，可从开始菜单启动 {#MyAppName}。',
           mbInformation, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('desktopicon') then
    CreateDesktopShortcutSafely;
end;
