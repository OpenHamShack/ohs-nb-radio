#ifndef AppExe
  #error Define AppExe before including self-update.iss
#endif

[Run]
; What an installer does when the program updates itself, shared by
; openhamshack-nb.iss and openhamshack-radio.iss (each #includes this, and defines
; AppExe, the program's .exe name, first).
;
; ohscore/update.py runs the downloaded installer, once the program has
; exited, with
;   /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /MERGETASKS=!plutodrivers /RELAUNCH=1
; An unattended install skips the "Launch" tick box ([Run]'s postinstall
; entry is skipifsilent), so nothing would start the program again and the
; operator would be left looking at a desktop. /RELAUNCH=1 is our own
; switch, read below: only an install started by the program itself starts
; it again, never a silent install an administrator runs for some other
; reason. runasoriginaluser: if Setup elevated itself (an install for all
; users), the program must still come back as the operator, not as an
; administrator.
;
; /MERGETASKS=!plutodrivers keeps the operator's earlier choices (the
; desktop icon) but never starts ADI's driver installer, elevated and with
; Windows' own trust question, in the middle of an update; a manual run of
; the installer still offers it (pluto-drivers.iss).
;
; [Run] comes first, before even these comments: this file is #included
; straight after pluto-drivers.iss, whose last section is [Code], and a ";"
; line there is Pascal, not a comment. Opening with a section header ends
; that [Code] before anything of ours is read.

Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: RelaunchAfterUpdate

[Code]
function RelaunchAfterUpdate(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:RELAUNCH|0}') = '1');
  if Result then
    Log('Started by the program''s own updater: starting it again');
end;
