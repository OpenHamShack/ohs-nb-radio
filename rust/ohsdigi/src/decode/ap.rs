//! A-priori (AP) bits from the operator's calls, as WSJT-X builds them.
//!
//! Ported from WSJT-X 2.7.0 (GPL-3): lib/ft8/ft8apset.f90 and the AP set-up
//! at the top of lib/ft4_decode.f90. Copyright (C) 2001-2024 Joe Taylor
//! K1JT, Steve Franke K9AN and the WSJT-X development team.
//!
//! Both pack a dummy standard message - FT8 "MYCALL DXCALL RRR", FT4
//! "MYCALL DXCALL RR73" - and use its first 58 bits (both calls) as what
//! the AP passes assume. Each refuses (no AP beyond CQ) when the message
//! does not pack as a standard i3=1 message that unpacks back to itself.

use crate::msg77::{pack77, unpack77, Bits77, CallHashes};

/// What the decoders need: the dummy message's payload, and whether the
/// DxCall half of it is real (AP types 3 and up need it).
#[derive(Clone, Copy, Debug)]
pub struct ApCalls {
    pub payload: Bits77,
    pub has_dxcall: bool,
}

fn trimmed(s: &str) -> String {
    s.trim().to_ascii_uppercase()
}

/// Pack `msg`; Some(bits) if it is a standard (i3=1) message that unpacks
/// to exactly itself.
fn standard(msg: &str) -> Option<Bits77> {
    let mut h = CallHashes::new();
    let p = pack77(msg.as_bytes(), &mut h).ok()?;
    if p.i3 != 1 {
        return None;
    }
    let bits = p.bits()?;
    let u = unpack77(&bits, true, &mut h);
    if !u.ok || u.text_lossy().trim() != msg {
        return None;
    }
    Some(bits)
}

/// ft8apset: MyCall and (optionally) DxCall to FT8's AP payload. With no
/// DxCall, WSJT-X packs the dummy "KA1ABC" and marks the DxCall bits
/// unusable. A nonstandard MyCall is tried in brackets, as ft8apset does
/// when stdcall() says so (here: when the plain form does not pack).
pub fn ft8_ap(mycall: &str, dxcall: &str) -> Option<ApCalls> {
    let my = trimmed(mycall);
    if my.len() < 3 {
        return None;
    }
    let dx = trimmed(dxcall);
    let (his, has_dxcall) = if dx.len() < 3 {
        ("KA1ABC".to_string(), false)
    } else {
        (dx, true)
    };
    let payload = standard(&format!("{my} {his} RRR")).or_else(|| standard(&format!("<{my}> {his} RRR")))?;
    Some(ApCalls { payload, has_dxcall })
}

/// ft4_decode's AP set-up: "MYCALL DXCALL RR73", with MyCall itself as the
/// dummy DxCall when there is none.
pub fn ft4_ap(mycall: &str, dxcall: &str) -> Option<ApCalls> {
    let my = trimmed(mycall);
    if my.len() < 3 {
        return None;
    }
    let dx = trimmed(dxcall);
    let (his, has_dxcall) = if dx.len() < 3 { (my.clone(), false) } else { (dx, true) };
    let payload = standard(&format!("{my} {his} RR73"))?;
    Some(ApCalls { payload, has_dxcall })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::decode::sim::hex_to_bits77;

    #[test]
    fn jt9s_dummy_calls() {
        // ft8code 2.7.0: "K1ABC W9XYZ RRR" and "K1ABC W9XYZ RR73".
        let a = ft8_ap("K1ABC", "W9XYZ").unwrap();
        assert_eq!(a.payload, hex_to_bits77("09bde3506149dc1fa488").unwrap());
        assert!(a.has_dxcall);
        let b = ft4_ap("k1abc", "W9XYZ").unwrap();
        assert_eq!(b.payload, hex_to_bits77("09bde3506149dc1f9d48").unwrap());
    }

    #[test]
    fn no_call_no_ap() {
        assert!(ft8_ap("", "W9XYZ").is_none());
        let a = ft8_ap("G4XYZ", "").unwrap();
        assert!(!a.has_dxcall);
    }
}
