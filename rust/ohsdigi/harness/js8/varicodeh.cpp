// varicodeh: JS8Call 2.2.0's own message layer (varicode.cpp, jsc.cpp,
// decodedtext.cpp, compiled unchanged) behind a stdin loop, so ohsdigi's
// src/js8/varicode.rs can be compared with it (tests/js8_golden.rs).
//
//   U <frame> <bits> <submode>      -> |message| <frame type>
//   B <submode> <mycall> <mygrid> <selected call or -> <force id 0/1> <force data 0/1> <text>
//                                   -> one "<frame> <bits>" per frame, then "."
#include <iostream>
#include <string>
#include <sstream>
#include <QString>
#include "varicode.h"
#include "decodedtext.h"

// DecodedText's other constructor calls WSJT-X's stdmsg_ (Fortran); the
// one used here does not, but the symbol must link.
extern "C" bool stdmsg_(char const *, bool, char const *, size_t, size_t) { return false; }

int main() {
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        std::istringstream in(line);
        std::string op;
        in >> op;
        if (op == "U") {
            std::string frame; int bits, sub;
            in >> frame >> bits >> sub;
            DecodedText d(QString::fromStdString(frame), bits, sub);
            std::cout << "|" << d.message().toStdString() << "| " << (int)d.frameType() << std::endl;
        } else if (op == "B") {
            int sub, fid, fdata; std::string mycall, mygrid, sel;
            in >> sub >> mycall >> mygrid >> sel >> fid >> fdata;
            std::string text;
            std::getline(in, text);
            if (!text.empty() && text[0] == ' ') text = text.substr(1);
            if (sel == "-") sel = "";
            auto frames = Varicode::buildMessageFrames(QString::fromStdString(mycall), QString::fromStdString(mygrid),
                QString::fromStdString(sel), QString::fromStdString(text), fid, fdata, sub);
            for (auto &f : frames) std::cout << f.first.toStdString() << " " << f.second << std::endl;
            std::cout << "." << std::endl;
        }
    }
}
