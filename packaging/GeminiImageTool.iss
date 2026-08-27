; GeminiImageTool 安装脚本 (Inno Setup 6)
; 打包便携版（内置 Python + 依赖 + app.py）为独立安装程序，目标机无需预装 Python。
;
; 使用前：把 StageDir 指向一个“完整便携目录”——即包含 python\ 运行时 + app.py + 支持文件
; 的干净副本（不要含 data\config.json、outputs\、__pycache__、unins000.* 等）。
; 编译：ISCC.exe GeminiImageTool.iss

#define MyAppName "GeminiImageTool"
#define MyAppVersion "2.2.1"
#define MyAppPublisher "GeminiImageTool"
; ↓↓↓ 改成你本机的完整便携目录（含 python\）
#define StageDir "C:\path\to\GeminiImageTool_portable"
#define OutDir "."

[Setup]
AppId={{37080BAB-16D8-4775-8186-3D286DB65C20}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename={#MyAppName}_Setup_v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\python\pythonw.exe
DisableDirPage=no
DisableReadyPage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式 / Create a desktop shortcut"; GroupDescription: "附加图标 / Additional icons:"

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """app.py"""; WorkingDir: "{app}"
Name: "{group}\{#MyAppName} (Console Mode)"; Filename: "{app}\Start.bat"; WorkingDir: "{app}"
Name: "{group}\创建桌面快捷方式 (Create Desktop Shortcut)"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\Create_Desktop_Shortcut.ps1"""; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """app.py"""; WorkingDir: "{app}"; Description: "立即启动 {#MyAppName} / Launch now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{autodesktop}\{#MyAppName}.lnk"
Type: filesandordirs; Name: "{app}\runtime\pycache"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
{ 桌面快捷方式用 COM best-effort 创建：普通桌面直接成功；桌面被重定向到
  不受信任装入点(如 OneDrive)时会抛异常，这里吞掉，绝不弹框中断安装。
  此类机器改由开始菜单“创建桌面快捷方式”手动创建（由资源管理器启动，不受 RedirectionGuard 限制）。}
procedure TryCreateDesktopShortcut;
var
  WshShell, Shortcut: Variant;
begin
  try
    WshShell := CreateOleObject('WScript.Shell');
    Shortcut := WshShell.CreateShortcut(ExpandConstant('{autodesktop}\{#MyAppName}.lnk'));
    Shortcut.TargetPath := ExpandConstant('{app}\python\pythonw.exe');
    Shortcut.Arguments := '"app.py"';
    Shortcut.WorkingDirectory := ExpandConstant('{app}');
    Shortcut.IconLocation := ExpandConstant('{app}\python\pythonw.exe');
    Shortcut.Description := '{#MyAppName}';
    Shortcut.Save;
  except
    { 桌面被重定向/受保护，静默跳过 }
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('desktopicon') then
    TryCreateDesktopShortcut;
end;
