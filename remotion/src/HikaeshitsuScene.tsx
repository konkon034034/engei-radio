import React from "react";
import {
    useCurrentFrame,
    useVideoConfig,
    AbsoluteFill,
    Audio,
    staticFile,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansJP";

const { fontFamily } = loadFont();

// ==========================================
// 控室トーク（エンディング）コンポーネント
// ==========================================
// 仕様（本編と同じレイアウト）:
// 1. 背景は真っ黒（背景画像なし）
// 2. キャラクターアイコンなし
// 3. テキストは黄色（本編と同じ配置）
// 4. 冒頭にジングル（音声とかぶってもOK）
// 5. 吹き出しアイコンなし
// ==========================================

interface HikaeshitsuLine {
    speaker: "カツミ" | "ヒロシ";
    text: string;
    startFrame: number;
    endFrame: number;
}

interface HikaeshitsuSceneProps {
    script: HikaeshitsuLine[];
    audioPath: string;
    bgmPath?: string;
    jinglePath?: string;
}

export const HikaeshitsuScene: React.FC<HikaeshitsuSceneProps> = ({
    script,
    audioPath,
    bgmPath,
    jinglePath = "hikaeshitsu_jingle.mp3",
}) => {
    const frame = useCurrentFrame();
    const { fps, durationInFrames, height, width } = useVideoConfig();

    // 現在の台本行
    const currentLine = script.find(
        (line) => frame >= line.startFrame && frame < line.endFrame
    );

    // 透過バー: 画面下部40%（本編と同じ）
    const barHeight = height * 0.40;
    const barY = height - barHeight;

    // フェードイン/アウト
    const fadeIn = Math.min(1, frame / 15);
    const fadeOut = Math.min(1, (durationInFrames - frame) / 15);
    const opacity = fadeIn * fadeOut;

    return (
        <AbsoluteFill style={{ opacity }}>
            {/* 黒背景（背景画像なし） */}
            <AbsoluteFill style={{ backgroundColor: "#000000" }} />

            {/* 冒頭ジングル（音声とかぶってもOK） */}
            {jinglePath && <Audio src={staticFile(jinglePath)} volume={0.3} />}

            {/* メイン音声トラック */}
            <Audio src={staticFile(audioPath)} />

            {/* BGM（あれば・小さめの音量） */}
            {bgmPath && <Audio src={staticFile(bgmPath)} volume={0.1} />}

            {/* チャンネル登録（上部・小さめ・ゆらゆら揺れ） */}
            <div
                style={{
                    position: "absolute",
                    top: 80,
                    left: 40,
                    right: 0,
                    fontFamily: fontFamily,
                    fontSize: 50,
                    fontWeight: "bold",
                    color: "rgba(255, 255, 0, 0.95)",
                    textShadow: [
                        "-4px -4px 0 #0055aa", "4px -4px 0 #0055aa",
                        "-4px 4px 0 #0055aa", "4px 4px 0 #0055aa",
                        "0 -4px 0 #0055aa", "0 4px 0 #0055aa",
                        "-4px 0 0 #0055aa", "4px 0 0 #0055aa",
                        "0 0 20px rgba(255,255,255,0.5)",
                    ].join(", "),
                    textAlign: "left",
                    // ゆらゆら上下揺れ（3秒周期、+-6px）
                    transform: `translateY(${Math.sin((frame / fps) * (Math.PI * 2 / 3)) * 6}px)`,
                }}
            >
                チャンネル登録よろしくね
            </div>

            {/* 控室にて（右端寄せ・スライドインのみ） */}
            <div
                style={{
                    position: "absolute",
                    top: 150,
                    right: 40,
                    fontFamily: fontFamily,
                    fontSize: 80,
                    fontWeight: "bold",
                    color: "#FFFFFF",
                    textShadow: [
                        "-6px -6px 0 #0055aa", "6px -6px 0 #0055aa",
                        "-6px 6px 0 #0055aa", "6px 6px 0 #0055aa",
                        "0 -6px 0 #0055aa", "0 6px 0 #0055aa",
                        "-6px 0 0 #0055aa", "6px 0 0 #0055aa",
                        "0 0 30px rgba(255,255,255,0.5)",
                    ].join(", "),
                    textAlign: "right",
                    // スライドイン（右から登場、20フレームで完了）
                    transform: `translateX(${Math.max(0, (1 - Math.min(1, frame / 20)) * 400)}px)`,
                    opacity: Math.min(1, frame / 15),
                }}
            >
                控室にて
            </div>

            {/* 透過バー（本編と同じ・画面下部40%） */}
            <div
                style={{
                    position: "absolute",
                    left: 0,
                    right: 0,
                    top: barY,
                    height: barHeight,
                    backgroundColor: "rgba(0, 0, 0, 0.75)",
                }}
            />

            {/* 字幕（本編と同じレイアウト・色だけ黄色） */}
            {currentLine && (
                <div
                    style={{
                        position: "absolute",
                        top: barY + 30,
                        left: 120,
                        right: 120,
                        fontFamily: fontFamily,
                        fontSize: 72,
                        fontWeight: "bold",
                        color: "#FFFF00",  // 黄色
                        textShadow: "4px 4px 10px rgba(0,0,0,0.95)",
                        textAlign: "center",
                        lineHeight: 1.25,
                        maxHeight: barHeight - 80,
                        overflow: "hidden",
                    }}
                >
                    {currentLine.text}
                </div>
            )}


        </AbsoluteFill>
    );
};

export default HikaeshitsuScene;
