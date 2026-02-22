import React from "react";
import { Composition, getInputProps } from "remotion";
import { DynamicNewsVideo } from "./DynamicNewsVideo";
import { HikaeshitsuScene } from "./HikaeshitsuScene";
import { NayamiOpening } from "./NayamiOpening";


// 動的プロパティを取得
const inputProps = getInputProps();

export const RemotionRoot: React.FC = () => {
    return (
        <>
            {/* ★ 動的ニュース動画（main.pyから呼び出し） */}
            <Composition
                id="DynamicNewsVideo"
                component={DynamicNewsVideo}
                durationInFrames={inputProps.durationInFrames || 13139}
                fps={24}
                width={1920}
                height={1080}
                defaultProps={{
                    title: inputProps.title || "テストタイトル",
                    channelName: inputProps.channelName || "もう枯らさない家庭園芸",
                    channelColor: inputProps.channelColor || "#228B22",
                    script: inputProps.script || [
                        { section: "main", speaker: "カツミ", text: "おはようございます！今日も年金ニュースをお届けしますよ！", emotion: "guts", startFrame: 0, endFrame: 120 },
                        { section: "main", speaker: "ヒロシ", text: "おはよう、カツミさん。今日はどんなニュースがあるの？", emotion: "default", startFrame: 120, endFrame: 240 },
                        { section: "main", speaker: "カツミ", text: "実は年金の支給額が来年から変わるらしいのよ！", emotion: "surprised", startFrame: 240, endFrame: 400 },
                        { section: "main", speaker: "ヒロシ", text: "えっ、本当？それは大事なニュースだね。", emotion: "surprised", startFrame: 400, endFrame: 520 },
                        { section: "main", speaker: "カツミ", text: "そうなの。みんなも知っておいた方がいいわよ。", emotion: "concerned", startFrame: 520, endFrame: 700 },
                        { section: "main", speaker: "ヒロシ", text: "しっかり確認しておかないとね。", emotion: "thinking", startFrame: 700, endFrame: 850 },
                    ],
                    audioPath: inputProps.audioPath || "audio.wav",
                    backgroundImage: inputProps.backgroundImage || "background.png",
                    katsumiImage: inputProps.katsumiImage || "katsumi_neutral.png",
                    hiroshiImage: inputProps.hiroshiImage || "hiroshi_neutral.png",
                    keyPoints: inputProps.keyPoints || [
                        "年金支給額が変わるって本当？！",
                        "物価上昇で年金は足りる？大丈夫？",
                        "申請しないと損する？！知らないと怖い"
                    ],
                    source: inputProps.source || "",
                    slideDuration: inputProps.slideDuration || 168,

                    hikaeshitsuJingle: inputProps.hikaeshitsuJingle || "hikaeshitsu_jingle.mp3",
                    subtitleStyle: inputProps.subtitleStyle || "highlight",
                    subtitleColor: inputProps.subtitleColor || "rgba(220,140,30,0.5)",
                    jakuchoQuote: inputProps.jakuchoQuote || "いくつになっても\n恋愛感情がなくなったわけでは\nないんです。\nただ、その表現の仕方が\n変わってきただけ。",
                    chartData: inputProps.chartData || [
                        { triggerFrame: 30, data: { type: "poll" as const, label: "年金受給開始年齢、あなたは？", value: 0, unit: "", items: [{ label: "60歳から", value: 25 }, { label: "65歳から", value: 45 }, { label: "70歳から", value: 20 }, { label: "まだ決めてない", value: 10 }] } },
                        { triggerFrame: 270, data: { type: "poll" as const, label: "この政策、賛成？反対？", value: 0, unit: "", items: [{ label: "賛成", value: 42 }, { label: "どちらとも言えない", value: 35 }, { label: "反対", value: 23 }] } },
                        { triggerFrame: 430, data: { type: "bar" as const, label: "年金増額率", value: 2.7, unit: "%", maxValue: 100 } },
                        { triggerFrame: 550, data: { type: "donut" as const, label: "受給者の割合", value: 65, unit: "%", maxValue: 100 } },
                        { triggerFrame: 720, data: { type: "number" as const, label: "標準月額年金", value: 230000, unit: "円" } },
                    ],
                }}
            />

            {/* ★ 控室トーク（main.pyから呼び出し） */}
            <Composition
                id="HikaeshitsuScene"
                component={HikaeshitsuScene}
                durationInFrames={inputProps.durationInFrames || 24 * 30}
                fps={24}
                width={1920}
                height={1080}
                defaultProps={{
                    script: inputProps.script || [],
                    audioPath: inputProps.audioPath || "hikaeshitsu_audio.wav",
                    bgmPath: inputProps.bgmPath || "hikaeshitsu_bgm.mp3",
                    jinglePath: inputProps.jinglePath || "hikaeshitsu_jingle.mp3",
                }}
            />

            {/* ★ 年金OPスライド（人物紹介＋状況説明） */}
            <Composition
                id="NayamiOpening"
                component={NayamiOpening}
                durationInFrames={inputProps.nayamiDuration || 480}
                fps={24}
                width={1920}
                height={1080}
                defaultProps={{
                    consultationText: inputProps.consultationText || "佐々木春子さん（仮名）。72歳、女性、一人暮らし。元小学校教員。月13万円の年金だけで生活している。65歳で夫を亡くし、それ以降ずっと一人。光熱費は節約のためテレビもつけない。食費は見切り品と自炊で月2万円に抑えている。趣味の絵画教室を開いているが、月謝収入はわずか。貯金を少しずつ切り崩す毎日。あなたは知っていますか？申請すればもらえるお金、見落としていませんか？",
                    consultationTitle: inputProps.consultationTitle || "月13万円で生きる72歳の現実",
                    consultantProfile: inputProps.consultantProfile || "72歳 女性 一人暮らし",
                    audioPath: inputProps.nayamiAudio || undefined,
                    jinglePath: inputProps.nayamiJingle || "hikaeshitsu_jingle.mp3",
                    durationInFrames: inputProps.nayamiDuration || 480,
                    colorScheme: inputProps.colorScheme || "nenkin",
                }}
            />

        </>
    );
};
