/* SPDX-License-Identifier: GPL-3.0-or-later
 * Offline test driver for pinned, unchanged VESC Tool packaging functions.
 * A local seccomp guard blocks networking. No GUI, transport or firmware
 * upload code is linked. Generated methods retain the upstream license notice.
 */
#include <QByteArray>
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDebug>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTextCodec>
#include <cerrno>
#include <cstddef>
#include <iostream>
#include <stdexcept>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include "vbytearray.h"

struct MessageOnly {
    void emitMessageDialog(QString, QString, bool) {
        throw std::runtime_error("Unexpected GUI/package branch");
    }
};
struct VescPackage { QByteArray lispData; };
class CodeLoader {
public:
    MessageOnly *mVesc = nullptr;
    static QString tr(const char *text) { return QString::fromUtf8(text); }
    QString reduceLispFile(QString);
    QByteArray lispPackImports(QString, QString, bool);
    QPair<QString, QList<QPair<QString, QByteArray>>> lispUnpackImports(QByteArray);
    bool getImportFromLine(QString, QString &, QString &, bool &);
    VescPackage unpackVescPackage(QByteArray) {
        throw std::runtime_error("Package imports are outside the local-file proof");
    }
};

// Exact method bodies extracted and hash-checked from dc53c658 codeloader.cpp.
#include "vesc_methods.inc"

static void deny_network() {
#define DENY(n) BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (n), 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM)
    sock_filter rules[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(seccomp_data, nr)),
        DENY(SYS_socket), DENY(SYS_connect), DENY(SYS_socketpair),
        DENY(SYS_sendto), DENY(SYS_sendmsg),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)
    };
    sock_fprog program = {static_cast<unsigned short>(sizeof rules / sizeof *rules), rules};
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) || prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program))
        throw std::runtime_error("Cannot install the offline guard");
    errno = 0;
    if (socket(AF_INET, SOCK_STREAM, 0) != -1 || errno != EPERM)
        throw std::runtime_error("Offline guard self-test failed");
}

static QString sha(const QByteArray &data) {
    return QString::fromLatin1(QCryptographicHash::hash(data, QCryptographicHash::Sha256).toHex());
}

int main(int argc, char **argv) {
    try {
        deny_network();
        QCoreApplication app(argc, argv);
        if (argc < 3) throw std::runtime_error("usage: vesc-payload-host lines SOURCE | pack SOURCE OUTPUT [LOCAL-CODEC]");
        QFile input(QString::fromLocal8Bit(argv[2]));
        if (!input.open(QIODevice::ReadOnly)) throw std::runtime_error("Cannot open input");
        const QByteArray raw = input.readAll();
        QTextCodec::ConverterState state;
        QString source = QTextCodec::codecForName("UTF-8")->toUnicode(raw.constData(), raw.size(), &state);
        if (state.invalidChars) throw std::runtime_error("Input must be valid UTF-8; no replacement decoding");
        CodeLoader loader;
        if (QByteArray(argv[1]) == "lines") {
            QJsonArray result;
            auto lines = source.split('\n');
            for (int i = 0; i < lines.size(); ++i) {
                QString path, tag;
                bool invalid = false;
                if (loader.getImportFromLine(lines[i], path, tag, invalid))
                    result.append(QJsonObject{{"line", i + 1}, {"path", path}, {"tag", tag}, {"invalid", invalid}});
            }
            std::cout << QJsonDocument(result).toJson(QJsonDocument::Compact).constData() << '\n';
            return 0;
        }
        if (QByteArray(argv[1]) != "pack" || argc < 4) throw std::runtime_error("Invalid mode or output");
        auto codec = QTextCodec::codecForName(argc > 4 ? argv[4] : "UTF-8");
        if (!codec) throw std::runtime_error("Unknown local codec");
        QTextCodec::setCodecForLocale(codec);
        // Never run VESC Tool's separate optional source reducer.
        const QByteArray payload = loader.lispPackImports(source, QFileInfo(input).canonicalPath(), false);
        if (payload.isEmpty()) throw std::runtime_error("VESC Tool refused the import layout");
        auto unpacked = loader.lispUnpackImports(payload);
        const int terminator = payload.indexOf('\0', 2);
        if (terminator < 2) throw std::runtime_error("Missing main terminator");
        const QByteArray mainBytes = payload.mid(2, terminator - 2);
        QJsonArray imports;
        for (auto item : unpacked.second)
            imports.append(QJsonObject{{"tag", item.first}, {"bytes", item.second.size()},
                                        {"sha256", sha(item.second)},
                                        {"data_base64", QString::fromLatin1(item.second.toBase64())}});
        QFile output(QString::fromLocal8Bit(argv[3]));
        if (!output.open(QIODevice::WriteOnly | QIODevice::NewOnly))
            throw std::runtime_error("Output already exists or cannot be created");
        if (output.write(payload) != payload.size()) throw std::runtime_error("Incomplete payload write");
        output.close();
        QJsonObject report{{"qt_version", qVersion()}, {"local_codec", QString::fromLatin1(codec->name())},
                           {"network_denied", true}, {"reduce_lisp", false}, {"payload_bytes", payload.size()},
                           {"payload_sha256", sha(payload)}, {"main_file_sha256", sha(raw)},
                           {"main_payload_sha256", sha(mainBytes)}, {"main_bytes_preserved", raw == mainBytes},
                           {"main_base64", QString::fromLatin1(mainBytes.toBase64())}, {"imports", imports}};
        std::cout << QJsonDocument(report).toJson(QJsonDocument::Compact).constData() << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 2;
    }
}
