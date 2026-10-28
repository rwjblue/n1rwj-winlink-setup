#include <QCoreApplication>
#include <QMediaDevices>
#include <QAudioDevice>
#include <QAudioFormat>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <cstdio>
int main(int argc, char **argv) {
 QCoreApplication app(argc, argv);
 QJsonArray rows;
 for (bool input : {false, true}) {
  for (auto d : input ? QMediaDevices::audioInputs() : QMediaDevices::audioOutputs()) {
   QAudioFormat f; f.setSampleRate(12000); f.setChannelCount(input ? 1 : 2); f.setSampleFormat(QAudioFormat::Float);
   rows.append(QJsonObject{{"name",d.description()},{"id",QString::fromUtf8(d.id())},{"input",input},{"qk4_format_supported",d.isFormatSupported(f)},{"preferred_rate",d.preferredFormat().sampleRate()},{"min_rate",d.minimumSampleRate()},{"max_rate",d.maximumSampleRate()}});
  }
 }
 puts(QJsonDocument(rows).toJson().constData());
}
