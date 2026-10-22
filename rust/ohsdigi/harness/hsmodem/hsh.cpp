// hsh - drives HSmodem's own transmitter and receiver code offline, so
// ohsdigi's port (rust/ohsdigi/src/hsmodem) can be held against it stage by
// stage. Built by build.sh against AMSAT-DL's QO-100-Modem source
// (github.com/amsat-dl/QO-100-Modem, the beacon's own tree) and the
// liquid-dsp library that tree ships (SharedLibs/x86_64/libliquid.so,
// "1.3.2"), unchanged: frame_packer.cpp, constellation.cpp, scrambler.cpp,
// crc16.cpp, fec.cpp (Schifra), symboltracker.cpp and liquid_if.cpp are
// HSmodem's files compiled as they are. This file only stands in for the
// parts of hsmodem.cpp and the sound card those files call, and replays
// HSmodem's receive loop (liquid_if.cpp demodulator(), hsmodem.cpp
// GRdata_rxdata()) with the stage values written out.
//
// HSmodem is (c) Kurt Moraw DJ0ABR, GPL (v2 or later in the file headers,
// GPL-3.0 in the repository's LICENSE); this harness is GPL-3.0-or-later.
// It is a test tool: it is never built into OpenHamShack.
//
//   hsh tx    <spec> <frames.out> <audio.f32 | syms.c64>
//   hsh rx    <audio48k.f32> <stages.out> <frames.out>
//   hsh rxiq  <iq.c64, 9600 S/s> <stages.out> <frames.out>
//   hsh rs    <codewords.in> <results.out>
//
// spec: records of 222 bytes: type, status, repeat, 219 payload bytes - the
//   arguments of HSmodem's Pack(). Each record is packed and sent through
//   _sendToModulator() exactly as distrubution.cpp does. The plain build
//   writes the 48 kHz sound-card audio (liquid_if.cpp modulator(), marker
//   tone off unless HSH_MARKER=1); the AMS build (-DAMS_TESTMODE, what the
//   beacon runs) writes the complex samples modulator() hands ams_testTX(),
//   one per symbol, scaled by its 0.9.
// frames.out (tx): the 258-byte frames Pack() returned, back to back.
// stages.out (rx): per received symbol, 8 float32: d_hat re, d_hat im (the
//   equaliser's output, i.e. the soft symbol), the hard symbol, symsync's
//   tau, the carrier NCO's frequency and phase, the AGC gain, and the
//   header-search outcome at this symbol (0 none, 1 frame, -1 FEC failed,
//   -2 CRC failed).
// frames.out (rx): one line per deframed frame: symbol index, then the 229
//   bytes getPayload() returns (10 management bytes + 219 payload) in hex.
// codewords.in (rs): 255-byte RS codewords; results.out: per codeword one
//   status byte (1 corrected, 0 failed) and the 223 data bytes.
//
// HSH_SPEED=<0-9> picks HSmodem's speed mode (default 9, the beacon's):
// the sound-card rate, interpolation, decimation and constellation are
// then that row of hsmodem.cpp's sr[], set before init_dsp() as
// startModem() sets them, so tx writes audio at that mode's rate (44100
// or 48000) and rx expects it.

#include "hsmodem.h"

#include <complex>
#include <vector>

// ---- what hsmodem.cpp and friends define, at the beacon's settings ------
// Speed mode 9 (hsmodem.cpp sr[]): 48000 Hz audio, TX interpolation 20, RX
// pre-decimation 5, 3 bits a symbol: 8APSK, 2400 Bd, 7200 bit/s. Other
// modes: HSH_SPEED, applied in main() from the copy of sr[] below.
int speedmode = 9;
int bitsPerSymbol = 3;
int constellationSize = 8;
int caprate = 48000;
int txinterpolfactor = 20;
int rxPreInterpolfactor = 5;
int linespeed = 7200;
int keeprunning = 1;
int speed = 0;
int io_capidx = 0, io_pbidx = 0, voice_pbidx = -1;
float pbvol = 1, capvol = 1, lsvol = 1;
int marker = 0;
int VoiceAudioMode = VOICEMODE_OFF;
int ann_running = 0, rtty_frequency = 0, rtty_txoff = 1, rx_in_sync = 0, rxlevel_deteced = 0;
int trigger_resetmodem = 0;
int UdpDataPort_ModemToApp = 40133;
char appIP[20] = {0};

// hsmodem.cpp's sr[] (audio, tx, rx, bpsym, linespeed; codec rate left
// out), copied: hsmodem.cpp itself is not compiled here.
static const int SR[10][5] = {
    {48000, 40, 10, 1, 1200}, {48000, 20, 5, 1, 2400},
    {48000, 32, 8, 2, 3000},  {48000, 24, 6, 2, 4000}, {44100, 20, 5, 2, 4410}, {48000, 20, 5, 2, 4800},
    {44100, 24, 6, 3, 5500},  {48000, 24, 6, 3, 6000}, {44100, 20, 5, 3, 6600}, {48000, 20, 5, 3, 7200},
};

static void set_speed(int m) {
    speedmode = m;
    caprate = SR[m][0];
    txinterpolfactor = SR[m][1];
    rxPreInterpolfactor = SR[m][2];
    bitsPerSymbol = SR[m][3];
    constellationSize = 1 << bitsPerSymbol;
    linespeed = SR[m][4];
}

static std::vector<float> audio_out;
static std::vector<std::complex<float>> syms_out;
static nco_crcf marker_nco = NULL;

int kmaudio_playsamples(int, float* p, int n, float) {
    audio_out.insert(audio_out.end(), p, p + n);
    return n;
}
int kmaudio_readsamples(int, float*, int, float, int) { return 0; }
uint8_t kmaudio_maxlevel(int) { return 0; }
int io_fifo_usedspace(int) { return 0; }
void io_fifo_clear(int) {}
int fifo_usedspace(int) { return 0; }
uint16_t* make_waterfall(float, int*) { return NULL; }
void sendUDP(char*, int, uint8_t*, int) {}
void sleep_ms(int) {}
void measure_speed_syms(int) {}
void GRdata_rxdata(uint8_t*, int, struct sockaddr_in*) {}
// tuning.cpp's 100 Hz marker, as init_tune() makes it.
float singleFrequency() {
    if (marker_nco == NULL) {
        marker_nco = nco_crcf_create(LIQUID_NCO);
        nco_crcf_set_frequency(marker_nco, 2.0f * (float)M_PI * 100.0f / (float)caprate);
    }
    nco_crcf_step(marker_nco);
    return nco_crcf_sin(marker_nco);
}
#ifdef AMS_TESTMODE
// ams_extension.cpp ams_testTX(): one complex sample per symbol, x0.9, to the
// Pluto driver. Kept as float; the driver's int32 scaling is not ours to copy.
void ams_testTX(liquid_float_complex s) {
    syms_out.push_back(std::complex<float>(s.real * 0.9f, s.imag * 0.9f));
}
#endif

// liquid_if.cpp's receive objects (globals there).
extern nco_crcf dnnco;
extern firdecim_crcf decim;
extern SYMTRACK* km_symtrack;
extern float radians_per_sample;
extern int getPayload_error;
void init_dsp();

static std::vector<uint8_t> readall(const char* fn) {
    std::vector<uint8_t> v;
    FILE* f = fopen(fn, "rb");
    if (!f) { perror(fn); exit(2); }
    uint8_t b[65536];
    size_t n;
    while ((n = fread(b, 1, sizeof b, f)) > 0) v.insert(v.end(), b, b + n);
    fclose(f);
    return v;
}

static void writeall(const char* fn, const void* p, size_t n) {
    FILE* f = fopen(fn, "wb");
    if (!f) { perror(fn); exit(2); }
    fwrite(p, 1, n, f);
    fclose(f);
}

static int cmd_tx(const char* spec, const char* frames_fn, const char* out_fn) {
    std::vector<uint8_t> s = readall(spec);
    std::vector<uint8_t> frames;
    marker = getenv("HSH_MARKER") && atoi(getenv("HSH_MARKER")) ? 1 : 0;
    for (size_t i = 0; i + 222 <= s.size(); i += 222) {
        int len = 0;
        uint8_t* tx = Pack(&s[i + 3], s[i], s[i + 1], &len, s[i + 2]);
        frames.insert(frames.end(), tx, tx + len);
        uint8_t copy[UDPBLOCKLEN];
        memcpy(copy, tx, len);
        _sendToModulator(copy, len);
    }
    writeall(frames_fn, frames.data(), frames.size());
#ifdef AMS_TESTMODE
    writeall(out_fn, syms_out.data(), syms_out.size() * sizeof(syms_out[0]));
#else
    writeall(out_fn, audio_out.data(), audio_out.size() * sizeof(float));
#endif
    return 0;
}

// hsmodem.cpp GRdata_rxdata()'s modem reset, with time counted in symbols
// rather than by the wall clock (getms()): offline, symbols are the clock.
// The FFT level detector's reset (trigger_resetmodem, set by fft.cpp when a
// signal appears) is not reproduced; ohsdigi does not port it either.
struct ResetLogic {
    long last = -1;
    void on_symbol(long n, bool frame) {
        if (frame) { last = n; rx_in_sync = 1; return; }
        if (last == -1) { last = n; return; }
        long tdiff = (long)((n - last) * 1000.0 * txinterpolfactor / caprate);
        int tmfrm_ms = (UDPBLOCKLEN * 8 * 1000) / linespeed;
        long elapsed_frames = tdiff / tmfrm_ms;
        if (tdiff > 5000) {
            if (elapsed_frames > 2) {
                rx_in_sync = 0;
                resetModem();
                last = n;
            }
        }
        if (elapsed_frames > 5) rx_in_sync = 0;
    }
};

static FILE* stages_f;
static FILE* frames_f;
static long nsym = 0;
static ResetLogic resets;

static void one_input(liquid_float_complex y) {
    unsigned int num_symbols_sync = 0;
    liquid_float_complex syms;
    unsigned int nsym_out = 0;
    km_symtrack_execute(km_symtrack, y, &syms, &num_symbols_sync, &nsym_out);
    if (num_symbols_sync == 0) return;
    uint8_t symb = nsym_out;
    if (bitsPerSymbol == 2) symb ^= (symb >> 1);
    getPayload_error = 0;
    uint8_t* pl = unpack_data(&symb, 1);
    float outcome = pl ? 1.0f : getPayload_error == 1 ? -1.0f : getPayload_error == 2 ? -2.0f : 0.0f;
    float st[8] = {syms.real, syms.imag, (float)nsym_out, symsync_crcf_get_tau(km_symtrack->symsync),
                   nco_crcf_get_frequency(km_symtrack->nco), nco_crcf_get_phase(km_symtrack->nco),
                   agc_crcf_get_gain(km_symtrack->agc), outcome};
    fwrite(st, sizeof st, 1, stages_f);
    if (pl) {
        fprintf(frames_f, "%ld ", nsym);
        for (int i = 0; i < PAYLOADLEN + 10; i++) fprintf(frames_f, "%02x", pl[i]);
        fprintf(frames_f, "\n");
    }
    resets.on_symbol(nsym, pl != NULL);
    nsym++;
}

static int cmd_rx(const char* in_fn, const char* stages_fn, const char* frames_fn, bool iq) {
    std::vector<uint8_t> raw = readall(in_fn);
    stages_f = fopen(stages_fn, "wb");
    frames_f = fopen(frames_fn, "w");
    if (!iq) {
        // liquid_if.cpp demodulator(), per sound-card sample.
        const float* a = (const float*)raw.data();
        size_t n = raw.size() / 4;
        liquid_float_complex ccol[16];
        int ccol_idx = 0;
        float last_rps = 0;
        for (size_t i = 0; i < n; i++) {
            float f = a[i];
            if (radians_per_sample != last_rps) {
                nco_crcf_set_frequency(dnnco, radians_per_sample);
                last_rps = radians_per_sample;
            }
            nco_crcf_step(dnnco);
            liquid_float_complex in, c;
            in.real = f;
            in.imag = f;
            nco_crcf_mix_down(dnnco, in, &c);
            ccol[ccol_idx++] = c;
            if (ccol_idx < rxPreInterpolfactor) continue;
            ccol_idx = 0;
            liquid_float_complex y;
            firdecim_crcf_execute(decim, ccol, &y);
            one_input(y);
        }
    } else {
        const liquid_float_complex* x = (const liquid_float_complex*)raw.data();
        size_t n = raw.size() / 8;
        for (size_t i = 0; i < n; i++) one_input(x[i]);
    }
    fclose(stages_f);
    fclose(frames_f);
    return 0;
}

static int cmd_rs(const char* in_fn, const char* out_fn) {
    std::vector<uint8_t> in = readall(in_fn);
    std::vector<uint8_t> out;
    for (size_t i = 0; i + 255 <= in.size(); i += 255) {
        uint8_t dst[255];
        memset(dst, 0, sizeof dst);
        int ok = cfec_Reconstruct(&in[i], dst);
        out.push_back(ok ? 1 : 0);
        out.insert(out.end(), dst, dst + 223);
    }
    writeall(out_fn, out.data(), out.size());
    return 0;
}

int main(int argc, char** argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: hsh tx|rx|rxiq|rs ...\n");
        return 2;
    }
    if (getenv("HSH_SPEED")) {
        int m = atoi(getenv("HSH_SPEED"));
        if (m < 0 || m > 9) {
            fprintf(stderr, "HSH_SPEED must be 0-9\n");
            return 2;
        }
        set_speed(m);
    }
    init_packer();
    initFEC();
    init_dsp();
    std::string cmd = argv[1];
    if (cmd == "tx" && argc == 5) return cmd_tx(argv[2], argv[3], argv[4]);
    if (cmd == "rx" && argc == 5) return cmd_rx(argv[2], argv[3], argv[4], false);
    if (cmd == "rxiq" && argc == 5) return cmd_rx(argv[2], argv[3], argv[4], true);
    if (cmd == "rs" && argc == 4) return cmd_rs(argv[2], argv[3]);
    fprintf(stderr, "bad arguments\n");
    return 2;
}
