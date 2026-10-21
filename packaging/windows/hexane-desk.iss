; Inno Setup (6.1 oder neuer) - Installer für Hexane Desk
; Bauen:  iscc /DAppVersion=0.1.0 packaging\windows\hexane-desk.iss      (vorher: pyinstaller packaging\hexane-desk.spec)
;
; Das Programm bringt seinen eigenen Python-Interpreter mit; Python muss nicht installiert sein.
; Geprüft/nachinstalliert werden: Microsoft Edge WebView2 (für das Programmfenster). Optional auf Wunsch: Tesseract und Poppler für OCR.
; Es wird nichts ohne Zustimmung aus dem Internet geladen. Downloads der optionalen Programme sind per SHA-256 festgelegt.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Hexane Desk"
#define CliExe "hexane-desk.exe"
#define GuiExe "hexane-desk-gui.exe"

#define PopplerUrl "https://github.com/oschwartz10612/poppler-windows/releases/download/v26.09.0-0/Release-26.09.0-0.zip"
#define PopplerSha "7a6f256a0ddf7536182246a5733331bf4677cbcc34f4663774947ad34556c8d0"
#define TessUrl    "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
#define TessSha    "c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9"
#define DeuUrl     "https://github.com/tesseract-ocr/tessdata_fast/raw/4.1.0/deu.traineddata"
#define DeuSha     "19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d"
#define WebView2Url "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

[Setup]
AppId={{B7F5C7A3-6D3E-4C5B-9F0A-2E5D3A9C1F42}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=DavionOL
AppPublisherURL=https://github.com/DavionOL/hexane-viewer-desktop
AppSupportURL=https://github.com/DavionOL/hexane-viewer-desktop/issues
DefaultDirName={autopf}\HexaneDesk
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\..\installer
OutputBaseFilename=HexaneDesk-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\..\LICENSE
UninstallDisplayIcon={app}\{#GuiExe}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Messages]
de.WelcomeLabel2=Dieses Programm installiert [name/ver] auf Ihrem Computer.%n%nPython oder andere Programme müssen nicht vorher installiert werden. Der Datensatz gehört nicht zum Lieferumfang, er wird nach dem Start im Programm gewählt.%n%nEs wird nichts ohne Ihre Zustimmung aus dem Internet geladen.

[Tasks]
Name: "desktopicon"; Description: "Symbol auf dem Desktop anlegen"; Flags: unchecked
Name: "webview2"; Description: "Microsoft Edge WebView2 installieren (nötig für das Programmfenster; ohne startet das Programm im Browser)"; Check: not WebView2Installed
Name: "ocr"; Description: "OCR für Scans installieren (lädt Tesseract und Poppler, rund 100 MB, benötigt Administratorrechte)"; Flags: unchecked

[Files]
Source: "..\..\dist\hexane-desk\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#GuiExe}"; Parameters: "desktop"
Name: "{autoprograms}\{#AppName} (Browser-Modus)"; Filename: "{app}\{#CliExe}"; Parameters: "serve"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#GuiExe}"; Parameters: "desktop"; Tasks: desktopicon

[Run]
Filename: "{app}\{#GuiExe}"; Parameters: "desktop"; Description: "{#AppName} jetzt starten"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\tools"

[Code]
var
  DownloadPage: TDownloadWizardPage;
  NeedDownload: Boolean;

function WebView2Installed: Boolean;
var
  pv: String;
  key: String;
begin
  Result := False;
  key := 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  if RegQueryStringValue(HKLM32, 'SOFTWARE\' + key, 'pv', pv) then
    Result := (pv <> '') and (pv <> '0.0.0.0');
  if (not Result) and RegQueryStringValue(HKLM64, 'SOFTWARE\' + key, 'pv', pv) then
    Result := (pv <> '') and (pv <> '0.0.0.0');
  if (not Result) and RegQueryStringValue(HKCU, 'Software\' + key, 'pv', pv) then
    Result := (pv <> '') and (pv <> '0.0.0.0');
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if Progress = ProgressMax then
    Log(Format('Download fertig: %s', [FileName]));
  Result := True;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), @OnDownloadProgress);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpReady then
  begin
    NeedDownload := False;
    DownloadPage.Clear;
    if WizardIsTaskSelected('webview2') then
    begin
      DownloadPage.Add('{#WebView2Url}', 'MicrosoftEdgeWebview2Setup.exe', '');
      NeedDownload := True;
    end;
    if WizardIsTaskSelected('ocr') then
    begin
      DownloadPage.Add('{#PopplerUrl}', 'poppler.zip', '{#PopplerSha}');
      DownloadPage.Add('{#TessUrl}', 'tesseract-setup.exe', '{#TessSha}');
      DownloadPage.Add('{#DeuUrl}', 'deu.traineddata', '{#DeuSha}');
      NeedDownload := True;
    end;
    if NeedDownload then
    begin
      DownloadPage.Show;
      try
        try
          DownloadPage.Download;
        except
          if DownloadPage.AbortedByUser then
            Log('Download vom Benutzer abgebrochen')
          else
            SuppressibleMsgBox('Der Download ist fehlgeschlagen oder die Prüfsumme stimmt nicht:' + #13#10 + GetExceptionMessage + #13#10#13#10 + 'Sie können die optionalen Punkte abwählen und trotzdem installieren.', mbError, MB_OK, IDOK);
          Result := False;
        end;
      finally
        DownloadPage.Hide;
      end;
    end;
  end;
end;

function RunTool(const FileName, Params: String; Elevate: Boolean): Boolean;
var
  ResultCode: Integer;
  Ok: String;
begin
  if Elevate then
    Result := ShellExec('runas', FileName, Params, '', SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode)
  else
    Result := Exec(FileName, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := Result and (ResultCode = 0);
  if Result then Ok := 'ok' else Ok := 'Fehler';
  Log(Format('%s %s -> %s (Code %d)', [FileName, Params, Ok, ResultCode]));
end;

procedure InstallOcrTools;
var
  ToolsDir, TessDir: String;
begin
  ToolsDir := ExpandConstant('{app}\tools');
  TessDir := ToolsDir + '\tesseract';
  ForceDirectories(ToolsDir);
  WizardForm.StatusLabel.Caption := 'Poppler wird eingerichtet …';
  if not RunTool('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath ''' +
       ExpandConstant('{tmp}\poppler.zip') + ''' -DestinationPath ''' + ToolsDir + '\poppler'' -Force"', False) then
    SuppressibleMsgBox('Poppler konnte nicht eingerichtet werden. Das Programm läuft trotzdem, nur PDFs werden langsamer gelesen.', mbError, MB_OK, IDOK);
  WizardForm.StatusLabel.Caption := 'Tesseract wird installiert (Bestätigung der Windows-Benutzerkontensteuerung nötig) …';
  if RunTool(ExpandConstant('{tmp}\tesseract-setup.exe'), '/S /D=' + TessDir, True) then
  begin
    ForceDirectories(TessDir + '\tessdata');
    FileCopy(ExpandConstant('{tmp}\deu.traineddata'), TessDir + '\tessdata\deu.traineddata', False);
  end
  else
    SuppressibleMsgBox('Tesseract konnte nicht installiert werden. OCR für Scans steht dann nicht zur Verfügung.', mbError, MB_OK, IDOK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('webview2') then
    begin
      WizardForm.StatusLabel.Caption := 'Microsoft Edge WebView2 wird installiert …';
      if not RunTool(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', False) then
        SuppressibleMsgBox('WebView2 konnte nicht installiert werden. Das Programm startet dann im Browser-Modus.', mbInformation, MB_OK, IDOK);
    end;
    if WizardIsTaskSelected('ocr') then
      InstallOcrTools;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserData: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    UserData := ExpandConstant('{localappdata}\hexane-desk');
    if DirExists(UserData) and (not UninstallSilent) then
      if MsgBox('Sollen auch der Suchindex, die Einstellungen und Ihre Markierungen gelöscht werden?' + #13#10#13#10 +
                'Der Index lässt sich neu aufbauen, Ihre Bewertungen und Notizen gehen dabei aber verloren.' + #13#10 +
                'Die Daten des Datensatzes selbst werden nie gelöscht.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(UserData, True, True, True);
  end;
end;
