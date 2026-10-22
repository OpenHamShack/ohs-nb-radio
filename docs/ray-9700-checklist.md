# IC-9700 checks for Ray

Thanks for proving the IC-9700 link on air. Four things are still
unconfirmed on a real radio; each takes a few minutes. Use OpenHamShack NB
0.1.10 or later (item 4 needs it). Transmit only where you normally would,
at your usual level - item 1 is a short carrier, nothing more.

**1. The CW correction (TX lock)**
1. Put the 9700 in **CW** and tune NB to a clear spot in the CW segment.
2. Key a **steady carrier for 3-4 seconds**, then unkey.
3. Note what the scope says: *LANDED +___ Hz*, and whether it then says
   *corrected for the next over*.
4. Key another 3-4 s carrier. Does it say **TX LOCKED**? Note any LANDED
   figure it shows this time.
5. Note **rigTxCorr** from the status strip.

**2. 23 cm on SUB**
1. Swap the bands so **23 cm is on SUB** (not MAIN).
2. Tune NB a few kHz. What does NB say, and what does the radio do? (NB
   expects to be refused and to ask whether 23 cm is on MAIN.)
3. Swap back to MAIN afterwards.

**3. Muting while you transmit**
Receive audio should go silent when you press PTT and come back about
two-thirds of a second after you let go.
- Do you hear the **start of your own voice** from the speaker before it
  mutes? Yes / no.
- Does audio come back at a sensible moment, without your own tail?
- If it is slow, try Settings > Transmitter > **Poll interval** 50 ms and
  say whether it is better.

**4. FM to SSB (new in 0.1.10)**
1. On receive, switch the 9700 to **FM**.
2. Within about a second NB should switch it back to **USB** and show a
   notice saying so. Did it?
3. If instead a notice says the radio **refused** the change, send the
   exact text.
4. Check the filter the radio picked for USB (FIL1/2/3) - is it the one you
   normally use?

Please send back the figures and answers for each item, plus your NB
version and the 9700's CI-V baud rate.
