; installer.iss -- the setup exe, built with Inno Setup 6 (https://jrsoftware.org/isinfo.php):
;
;   iscc installer\installer.iss   -> installer\dist\enoughy-setup.exe
;
; What install.ps1 does, as an exe: it asks which account is the child's and for
; the parent's server, unpacks its own Python (bundled from installer\build\python, which
; build-python.ps1 makes), copies the monitor into C:\ProgramData\Enoughy and
; locks it, the widget into the shared folder, puts the "Extra time" shortcut on
; the shared desktop and registers the two tasks.
; It shows up in Apps & Features; that uninstall removes all of it. The wizard
; sections below are Inno's own; the [Code] section is Pascal, run by the exe.
;
; Not yet, next to install.ps1: moving a ScreenTime or pre-0.5 install, and a
; choice of folder for the shortcut.

#define FileHandle FileOpen("..\monitor\VERSION")
#define Version Trim(FileRead(FileHandle))
#expr FileClose(FileHandle)

#define MonitorDir "{commonappdata}\Enoughy"
#define SharedDir  "{commonappdata}\EnoughyShared"
#define PythonDir  "{commonappdata}\EnoughyPython"

[Setup]
AppId=enoughy
AppName=enoughy
AppVersion={#Version}
AppPublisher=enoughy.com
DefaultDirName={#MonitorDir}
DisableDirPage=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=no
; Not in the locked {app}: Apps & Features starts the uninstaller unelevated,
; so it must be readable by everyone, and writable only by administrators.
UninstallFilesDir={commonpf}\enoughy
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=enoughy-setup
WizardStyle=modern
; The monitor starts at boot; the widget when the child logs in.
AlwaysRestart=yes
; Writes "Setup Log <date> #<n>.txt" to the running account's Temp folder.
SetupLogging=yes

[Files]
Source: "..\monitor\monitor.py";      DestDir: "{app}"
Source: "..\monitor\os_tooling.py";   DestDir: "{app}"
Source: "..\monitor\remote_sync.py";  DestDir: "{app}"
Source: "..\monitor\config.py";       DestDir: "{app}"
Source: "..\monitor\settings.py";     DestDir: "{app}"
Source: "..\monitor\VERSION";         DestDir: "{app}"
Source: "..\monitor\launcher.ps1";    DestDir: "{app}"
Source: "..\monitor\release_key.cer"; DestDir: "{app}"
Source: "..\widget\remaining_time_widget.py"; DestDir: "{#SharedDir}"
; A running monitor holds the DLLs; Setup closes it, or replaces them at the reboot.
Source: "build\python\*"; DestDir: "{#PythonDir}"; Flags: recursesubdirs ignoreversion restartreplace

[Dirs]
Name: "{app}\data\{code:Child}"
Name: "{#SharedDir}\{code:Child}"

[Icons]
; Opens the redeem file; the child pastes a code into it.
Name: "{commondesktop}\Extra time"; Filename: "{#SharedDir}\{code:Child}\extra_time.txt"

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/End /TN EnoughyMonitor";       Flags: runhidden; RunOnceId: "end-monitor"
Filename: "{sys}\schtasks.exe"; Parameters: "/End /TN EnoughyWidget";        Flags: runhidden; RunOnceId: "end-widget"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN EnoughyMonitor /F"; Flags: runhidden; RunOnceId: "delete-monitor"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN EnoughyWidget /F";  Flags: runhidden; RunOnceId: "delete-widget"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{#SharedDir}"
Type: filesandordirs; Name: "{#PythonDir}"

[Code]
const
  DefaultServerUrl = 'https://marwin.pfranek.cz';   // the author's server; a child token from it is what turns syncing on

var
  AccountPage: TInputOptionWizardPage;
  ServerPage: TInputQueryWizardPage;
  NewSecret: String;   // generated on a fresh install, shown at the end
  Accounts: TArrayOfString;   // the local account names, one per row of the account page

function Child(Param: String): String;
begin
  Result := Accounts[AccountPage.SelectedValueIndex];
end;

// Not {app}: the token page reads this folder before the wizard has set {app}.
function ChildDataDir: String;   begin Result := ExpandConstant('{#MonitorDir}\data\') + Child(''); end;
function ChildSharedDir: String; begin Result := ExpandConstant('{#SharedDir}\') + Child(''); end;

// One row per enabled local account, from WMI; a typed name invites a typo that
// would leave the monitor watching an account nobody uses. Behind a Microsoft
// account Windows puts a name like "peter_fwx12", so the row shows the person too.
procedure ListAccounts;
var
  Locator, Service, Users, User, FullName: Variant;
  I: Integer;
  Caption: String;
begin
  Locator := CreateOleObject('WbemScripting.SWbemLocator');
  Service := Locator.ConnectServer('', 'root\cimv2');
  Users := Service.ExecQuery('SELECT Name, FullName FROM Win32_UserAccount WHERE LocalAccount = TRUE AND Disabled = FALSE');
  SetArrayLength(Accounts, Users.Count);
  for I := 0 to Users.Count - 1 do begin
    User := Users.ItemIndex(I);
    Accounts[I] := User.Name;
    Caption := Accounts[I];
    FullName := User.FullName;
    if not VarIsNull(FullName) and (FullName <> '') and (CompareText(FullName, Accounts[I]) <> 0) then
      Caption := Caption + '   (' + FullName + ')';
    AccountPage.Add(Caption);
  end;
end;

procedure InitializeWizard;
var
  I, Candidates, LastCandidate: Integer;
begin
  AccountPage := CreateInputOptionPage(wpWelcome, 'Child account', 'Which local account is the child''s?',
    'The monitor counts the time this account is logged in and shuts the computer down when it is up.', True, False);
  ListAccounts;
  Candidates := 0;
  for I := 0 to GetArrayLength(Accounts) - 1 do begin
    // Preselected when it is the only one besides the parent running this and Windows' own.
    if (CompareText(Accounts[I], GetUserNameString) <> 0) and (Pos(' ' + Lowercase(Accounts[I]) + ' ', ' guest defaultaccount wdagutilityaccount ') = 0) then begin
      Candidates := Candidates + 1;
      LastCandidate := I;
    end;
  end;
  if Candidates = 1 then AccountPage.Values[LastCandidate] := True;

  ServerPage := CreateInputQueryPage(AccountPage.ID, 'Parent''s server', 'Where does the monitor report to?',
    'The child token comes from add_child.py on the parent''s server. Leave it empty to run without syncing; then the server is never contacted.');
  ServerPage.Add('Child token:', False);
  ServerPage.Add('Server URL:', False);
end;

function ReadFile(FileName, Default: String): String;
var
  S: AnsiString;
begin
  Result := Default;
  if LoadStringFromFile(FileName, S) and (Trim(S) <> '') then Result := Trim(S);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  // A reinstall shows what it has; Enter keeps it, like install.ps1.
  if CurPageID = ServerPage.ID then begin
    ServerPage.Values[0] := ReadFile(ChildDataDir + '\child_token.txt', '');
    ServerPage.Values[1] := ReadFile(ChildDataDir + '\server_url.txt', DefaultServerUrl);
  end;
  if (CurPageID = wpFinished) and (NewSecret <> '') then
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 +
      'Shared secret, needed by grant_extra_time_offline.py on your own machine (it stays in ' +
      ChildDataDir + '\secret.txt here):' + #13#10 + NewSecret;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = AccountPage.ID) and (AccountPage.SelectedValueIndex < 0) then begin
    MsgBox('Pick the child''s account.', mbError, MB_OK);
    Result := False;
  end;
end;

procedure Run(Exe, Args, What: String);
var
  Code: Integer;
begin
  if not Exec(ExpandConstant(Exe), ExpandConstant(Args), '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
    RaiseException(ExpandConstant(What) + ' failed (exit code ' + IntToStr(Code) + ').');
end;

// 16 random bytes from Windows' own generator, as hex.
function BCryptGenRandom(Algorithm: Integer; Buffer: AnsiString; Count, Flags: Integer): Integer;
  external 'BCryptGenRandom@bcrypt.dll stdcall';

function RandomHex: String;
var
  Buffer: AnsiString;
  I: Integer;
begin
  SetLength(Buffer, 16);
  if BCryptGenRandom(0, Buffer, 16, 2) <> 0 then RaiseException('Windows gave no random bytes for the secret.');   // 2 = system-preferred RNG
  for I := 1 to 16 do Result := Result + Format('%.2x', [Ord(Buffer[I])]);
end;

// Both credentials go to files in the locked data folder. A fresh install gets
// a random secret for signing extra-time codes; a reinstall keeps the one it has.
procedure WriteCredentials;
var
  Token, UpdateMode: String;
begin
  if not FileExists(ChildDataDir + '\secret.txt') then begin
    NewSecret := RandomHex;
    SaveStringToFile(ChildDataDir + '\secret.txt', NewSecret, False);
  end;
  Token := Trim(ServerPage.Values[0]);
  if Token <> '' then SaveStringToFile(ChildDataDir + '\child_token.txt', Token, False);
  SaveStringToFile(ChildDataDir + '\server_url.txt', Trim(ServerPage.Values[1]), False);
  // `auto` fetches releases at boot, `manual` stays as installed; the default is
  // auto with a token and manual offline. Edit the file to change it; a reinstall keeps it.
  if not FileExists(ExpandConstant('{app}\UPDATE_MODE')) then begin
    if Token <> '' then UpdateMode := 'auto' else UpdateMode := 'manual';
    SaveStringToFile(ExpandConstant('{app}\UPDATE_MODE'), UpdateMode, False);
  end;
end;

// The same task install.ps1 registers: runs on battery, never times out. The
// definition comes from the Task Scheduler API, but schtasks registers it: the
// API's register call wants a null password, which this script cannot pass.
procedure RegisterTask(Name: String; TriggerType: Integer; UserId: String; LogonType: Integer; RunLevel: Integer; Exe, Args, WorkDir: String);
var
  Service, Task, Settings, Trigger, Action, Principal: Variant;
  Xml, XmlFile: String;
  Stream: TFileStream;
begin
  Service := CreateOleObject('Schedule.Service');
  Service.Connect();
  Task := Service.NewTask(0);
  Settings := Task.Settings;
  Settings.DisallowStartIfOnBatteries := False;
  Settings.StopIfGoingOnBatteries := False;
  Settings.ExecutionTimeLimit := 'PT0S';
  Trigger := Task.Triggers.Create(TriggerType);
  if TriggerType = 9 then Trigger.UserId := UserId;   // logon of this account only
  Action := Task.Actions.Create(0);   // run a program
  Action.Path := Exe;
  Action.Arguments := Args;
  Action.WorkingDirectory := WorkDir;
  Principal := Task.Principal;
  Principal.UserId := UserId;
  Principal.LogonType := LogonType;
  Principal.RunLevel := RunLevel;
  Xml := #$FEFF + Task.XmlText;   // BOM + UTF-16, the encoding the XML declares and schtasks reads
  XmlFile := ExpandConstant('{tmp}\') + Name + '.xml';
  Stream := TFileStream.Create(XmlFile, fmCreate);
  try Stream.Write(Xml, Length(Xml) * 2); finally Stream.Free; end;
  Run('{sys}\schtasks.exe', '/Create /TN ' + Name + ' /XML "' + XmlFile + '" /F', 'Registering the task ' + Name);
end;

var
  Step: String;   // named in the error when a post-install step fails

procedure At(Name: String);
begin
  Step := Name;
  Log('enoughy: ' + Name);
end;

procedure PostInstall;
begin
  // monitor.py runs as SYSTEM on this interpreter, so the child must not be able to
  // write into it: SYSTEM and Administrators full, Users read-only.
  At('locking the Python folder');
  Run('{sys}\icacls.exe', '"{#PythonDir}" /inheritance:r /grant *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F *S-1-5-32-545:(OI)(CI)RX', 'Locking {#PythonDir}');
  // The monitor folder: SYSTEM and Administrators only. That lock is what stops
  // the child reading secret.txt and forging codes, so it comes before the secret.
  At('locking the monitor folder');
  Run('{sys}\icacls.exe', '"{app}" /inheritance:r /grant *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F', 'Locking {app}');
  At('writing the credentials'); WriteCredentials;
  // The shared folder: every local account may write. It holds only the widget
  // and, per child, the number it shows and the redeem file, nothing trusted.
  At('opening the shared folder');
  Run('{sys}\icacls.exe', '"{#SharedDir}" /grant *S-1-5-32-545:(OI)(CI)M', 'Opening {#SharedDir}');
  if not FileExists(ChildSharedDir + '\extra_time.txt') then SaveStringToFile(ChildSharedDir + '\extra_time.txt', '', False);
  // Task 1: the launcher as SYSTEM at every boot; it starts monitor.py and installs releases.
  At('registering the monitor task');
  RegisterTask('EnoughyMonitor', 8, 'SYSTEM', 5, 1, 'powershell.exe',
    ExpandConstant('-NoProfile -ExecutionPolicy Bypass -File "{app}\launcher.ps1"'), ExpandConstant('{app}'));
  // Task 2: the overlay in the child's session when they log in.
  At('registering the widget task');
  RegisterTask('EnoughyWidget', 9, Child(''), 3, 0, ExpandConstant('{#PythonDir}\pythonw.exe'),
    ExpandConstant('"{#SharedDir}\remaining_time_widget.py" "') + ChildSharedDir + '\remaining_time.txt"', ExpandConstant('{#SharedDir}'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then Exit;   // the files are copied, the wizard is answered
  try
    PostInstall;
  except
    RaiseException('While ' + Step + ': ' + GetExceptionMessage);
  end;
end;
