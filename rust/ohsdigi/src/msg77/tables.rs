// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Tables copied from WSJT-X 2.7.0, lib/77bit/packjt77.f90, copyright (C)
// 2001-2023 Joe Taylor K1JT and the WSJT Development Group,
// GPL-3.0-or-later. Their order is part of the protocol: the index is
// what goes over the air.

/// ARRL/RAC sections for ARRL Field Day (types 0.3 and 0.4), 7 bits,
/// index 1-based on the air. Each blank-padded to 3, as in WSJT-X.
pub const ARRL_SECTIONS: [&[u8; 3]; 86] = [
    b"AB ", b"AK ", b"AL ", b"AR ", b"AZ ", b"BC ", b"CO ", b"CT ", b"DE ", b"EB ", b"EMA", b"ENY", b"EPA", b"EWA",
    b"GA ", b"GH ", b"IA ", b"ID ", b"IL ", b"IN ", b"KS ", b"KY ", b"LA ", b"LAX", b"NS ", b"MB ", b"MDC", b"ME ",
    b"MI ", b"MN ", b"MO ", b"MS ", b"MT ", b"NC ", b"ND ", b"NE ", b"NFL", b"NH ", b"NL ", b"NLI", b"NM ", b"NNJ",
    b"NNY", b"TER", b"NTX", b"NV ", b"OH ", b"OK ", b"ONE", b"ONN", b"ONS", b"OR ", b"ORG", b"PAC", b"PR ", b"QC ",
    b"RI ", b"SB ", b"SC ", b"SCV", b"SD ", b"SDG", b"SF ", b"SFL", b"SJV", b"SK ", b"SNJ", b"STX", b"SV ", b"TN ",
    b"UT ", b"VA ", b"VI ", b"VT ", b"WCF", b"WI ", b"WMA", b"WNY", b"WPA", b"WTX", b"WV ", b"WWA", b"WY ", b"DX ",
    b"PE ", b"NB ",
];

/// US states, Canadian provinces and DX entities' multipliers for the ARRL
/// RTTY Roundup (type 3), sent as 8000 + index (1-based).
pub const RTTY_MULTS: [&[u8; 3]; 171] = [
    b"AL ", b"AK ", b"AZ ", b"AR ", b"CA ", b"CO ", b"CT ", b"DE ", b"FL ", b"GA ", b"HI ", b"ID ", b"IL ", b"IN ",
    b"IA ", b"KS ", b"KY ", b"LA ", b"ME ", b"MD ", b"MA ", b"MI ", b"MN ", b"MS ", b"MO ", b"MT ", b"NE ", b"NV ",
    b"NH ", b"NJ ", b"NM ", b"NY ", b"NC ", b"ND ", b"OH ", b"OK ", b"OR ", b"PA ", b"RI ", b"SC ", b"SD ", b"TN ",
    b"TX ", b"UT ", b"VT ", b"VA ", b"WA ", b"WV ", b"WI ", b"WY ", b"NB ", b"NS ", b"QC ", b"ON ", b"MB ", b"SK ",
    b"AB ", b"BC ", b"NWT", b"NF ", b"LB ", b"NU ", b"YT ", b"PEI", b"DC ", b"DR ", b"FR ", b"GD ", b"GR ", b"OV ",
    b"ZH ", b"ZL ", b"X01", b"X02", b"X03", b"X04", b"X05", b"X06", b"X07", b"X08", b"X09", b"X10", b"X11", b"X12",
    b"X13", b"X14", b"X15", b"X16", b"X17", b"X18", b"X19", b"X20", b"X21", b"X22", b"X23", b"X24", b"X25", b"X26",
    b"X27", b"X28", b"X29", b"X30", b"X31", b"X32", b"X33", b"X34", b"X35", b"X36", b"X37", b"X38", b"X39", b"X40",
    b"X41", b"X42", b"X43", b"X44", b"X45", b"X46", b"X47", b"X48", b"X49", b"X50", b"X51", b"X52", b"X53", b"X54",
    b"X55", b"X56", b"X57", b"X58", b"X59", b"X60", b"X61", b"X62", b"X63", b"X64", b"X65", b"X66", b"X67", b"X68",
    b"X69", b"X70", b"X71", b"X72", b"X73", b"X74", b"X75", b"X76", b"X77", b"X78", b"X79", b"X80", b"X81", b"X82",
    b"X83", b"X84", b"X85", b"X86", b"X87", b"X88", b"X89", b"X90", b"X91", b"X92", b"X93", b"X94", b"X95", b"X96",
    b"X97", b"X98", b"X99",
];
