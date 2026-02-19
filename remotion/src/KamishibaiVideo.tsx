import React from "react";
import {
    AbsoluteFill,
    Img,
    Audio,
    Sequence,
    useCurrentFrame,
    interpolate,
    spring,
    useVideoConfig,
    staticFile,
} from "remotion";

/**
 * 紙芝居動画コンポーネント
 * - 6枚のPillow生成画像をスライドショー形式で表示
 * - 各スライドに音声を同期
 * - スライド間にトランジション（クロスフェード）
 * - 字幕表示
 */

interface KamishibaiSlide {
    image: string;         // 画像パス (public/内)
    audioPath: string;     // 音声パス
    durationFrames: number; // このスライドの表示フレーム数
    subtitle: string;      // 字幕テキスト
    tag: string;           // hook, causes, solutions, before_after, summary, hikaeshitsu
}

interface KamishibaiProps {
    slides: KamishibaiSlide[];
    bgmPath?: string;
    bgmVolume?: number;
    channelName?: string;
    channelColor?: string;
    durationInFrames: number;
}

const TRANSITION_FRAMES = 12; // 0.5秒のクロスフェード

const SlideView: React.FC<{
    slide: KamishibaiSlide;
    isActive: boolean;
    progress: number;
}> = ({ slide, isActive, progress }) => {
    const frame = useCurrentFrame();
    const { fps } = useVideoConfig();

    // フェードイン
    const opacity = interpolate(
        progress,
        [0, 0.05, 0.95, 1],
        [0, 1, 1, 0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
    );

    // 微妙なズームアニメーション（Ken Burns効果）
    const scale = interpolate(
        progress,
        [0, 1],
        [1.0, 1.03],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
    );

    return (
        <AbsoluteFill style={{ opacity }}>
            {/* 背景画像 */}
            <AbsoluteFill style={{
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
                overflow: "hidden",
            }}>
                <Img
                    src={staticFile(slide.image)}
                    style={{
                        width: "100%",
                        height: "100%",
                        objectFit: "cover",
                        transform: `scale(${scale})`,
                    }}
                />
            </AbsoluteFill>
        </AbsoluteFill>
    );
};

export const KamishibaiVideo: React.FC<KamishibaiProps> = ({
    slides,
    bgmPath = "hikaeshitsu_bgm.mp3",
    bgmVolume = 0.15,
    channelName = "",
    channelColor = "#8B4513",
    durationInFrames,
}) => {
    const frame = useCurrentFrame();
    const { fps } = useVideoConfig();

    // 各スライドの開始フレームを計算
    let currentStart = 0;
    const slideTimings = slides.map((slide) => {
        const start = currentStart;
        currentStart += slide.durationFrames;
        return { ...slide, startFrame: start, endFrame: start + slide.durationFrames };
    });

    // 現在のスライドを特定
    const currentSlideIndex = slideTimings.findIndex(
        (s) => frame >= s.startFrame && frame < s.endFrame
    );

    // スライド進行度（0-1）
    const totalFrames = slideTimings.length > 0
        ? slideTimings[slideTimings.length - 1].endFrame
        : durationInFrames;
    const overallProgress = frame / totalFrames;

    return (
        <AbsoluteFill style={{ backgroundColor: "#000" }}>
            {/* スライド表示 */}
            {slideTimings.map((slide, index) => {
                const slideFrame = frame - slide.startFrame;
                const progress = slideFrame / slide.durationFrames;
                const isActive = index === currentSlideIndex;

                if (frame < slide.startFrame - TRANSITION_FRAMES || frame > slide.endFrame + TRANSITION_FRAMES) {
                    return null;
                }

                return (
                    <Sequence
                        key={index}
                        from={slide.startFrame}
                        durationInFrames={slide.durationFrames}
                    >
                        <SlideView
                            slide={slide}
                            isActive={isActive}
                            progress={interpolate(
                                frame - slide.startFrame,
                                [0, slide.durationFrames],
                                [0, 1],
                                { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
                            )}
                        />
                        {/* スライド音声 */}
                        {slide.audioPath && (
                            <Audio src={staticFile(slide.audioPath)} volume={1} />
                        )}
                    </Sequence>
                );
            })}

            {/* スライドインジケーター（画面上部中央） */}
            <div style={{
                position: "absolute",
                top: 12,
                left: "50%",
                transform: "translateX(-50%)",
                display: "flex",
                gap: 8,
                zIndex: 10,
            }}>
                {slides.map((_, i) => (
                    <div
                        key={i}
                        style={{
                            width: i === currentSlideIndex ? 24 : 10,
                            height: 10,
                            borderRadius: 5,
                            backgroundColor: i === currentSlideIndex
                                ? channelColor
                                : "rgba(255,255,255,0.4)",
                            transition: "all 0.3s",
                        }}
                    />
                ))}
            </div>

            {/* プログレスバー（画面最下部） */}
            <div style={{
                position: "absolute",
                bottom: 0,
                left: 0,
                width: `${overallProgress * 100}%`,
                height: 4,
                backgroundColor: channelColor,
                zIndex: 10,
            }} />

            {/* BGM */}
            {bgmPath && (
                <Audio
                    src={staticFile(bgmPath)}
                    volume={bgmVolume}
                    loop
                />
            )}
        </AbsoluteFill>
    );
};
