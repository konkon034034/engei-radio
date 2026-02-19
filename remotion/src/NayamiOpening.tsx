import React from "react";
import {
    AbsoluteFill,
    Audio,
    Img,
    interpolate,
    useCurrentFrame,
    useVideoConfig,
    staticFile,
    Sequence,
} from "remotion";

const fontFamily = "'Noto Sans JP', 'Hiragino Kaku Gothic ProN', sans-serif";

const COLOR_SCHEMES = {
    nenkin: {
        bg: "#1a0808",
        textColor: "#ffe0e0",
        textStroke: "#d45050",
        titleColor: "#ffb8b8",
        titleBg: "rgba(212,60,60,0.25)",
        titleBorder: "rgba(255,140,140,0.5)",
        profileBg: "rgba(212,60,60,0.20)",
        borderColor: "rgba(255,140,140,0.30)",
        boxBg: "rgba(30,8,8,0.92)",
        accentColor: "#ff7070",
        decorColor: "rgba(255,100,100,0.12)",
        keywordColor: "#ffcc00",
    },
    sakura: {
        bg: "#1a0a12",
        textColor: "#ffe0ec",
        textStroke: "#d4508a",
        titleColor: "#ffb8d4",
        titleBg: "rgba(212,80,138,0.25)",
        titleBorder: "rgba(255,150,190,0.5)",
        profileBg: "rgba(212,80,138,0.20)",
        borderColor: "rgba(255,150,190,0.30)",
        boxBg: "rgba(30,10,20,0.92)",
        accentColor: "#ff90c0",
        decorColor: "rgba(255,120,180,0.12)",
        keywordColor: "#ffcc00",
    },
    fuji: {
        bg: "#110820",
        textColor: "#e8d4ff",
        textStroke: "#8a50d4",
        titleColor: "#d4b0ff",
        titleBg: "rgba(138,80,212,0.25)",
        titleBorder: "rgba(190,140,255,0.5)",
        profileBg: "rgba(138,80,212,0.20)",
        borderColor: "rgba(180,140,255,0.30)",
        boxBg: "rgba(20,10,40,0.92)",
        accentColor: "#b090ff",
        decorColor: "rgba(170,120,255,0.12)",
        keywordColor: "#80ffcc",
    },
    kinmokusei: {
        bg: "#1a1408",
        textColor: "#fff0d4",
        textStroke: "#d49030",
        titleColor: "#ffd490",
        titleBg: "rgba(212,144,48,0.25)",
        titleBorder: "rgba(255,200,120,0.5)",
        profileBg: "rgba(212,144,48,0.20)",
        borderColor: "rgba(255,200,120,0.30)",
        boxBg: "rgba(40,25,8,0.92)",
        accentColor: "#ffb060",
        decorColor: "rgba(255,180,80,0.12)",
        keywordColor: "#80d4ff",
    },
} as const;

export type ColorSchemeName = keyof typeof COLOR_SCHEMES;

export interface NayamiOpeningProps {
    consultationText: string;
    consultationTitle: string;
    consultantProfile: string;
    audioPath?: string;
    jinglePath: string;
    durationInFrames: number;
    colorScheme?: ColorSchemeName;
}

export const NayamiOpening: React.FC<NayamiOpeningProps> = ({
    consultationText,
    consultationTitle,
    consultantProfile,
    audioPath,
    jinglePath,
    durationInFrames,
    colorScheme = "nenkin",
}) => {
    const frame = useCurrentFrame();
    const { fps } = useVideoConfig();
    const colors = COLOR_SCHEMES[colorScheme];

    const headerFadeIn = interpolate(frame, [fps * 0.5, fps * 1.5], [0, 1], {
        extrapolateLeft: "clamp", extrapolateRight: "clamp",
    });
    const textStart = fps * 2;
    const textFadeIn = interpolate(frame, [textStart, textStart + fps * 0.5], [0, 1], {
        extrapolateLeft: "clamp", extrapolateRight: "clamp",
    });
    const decorFloat = interpolate(frame, [0, fps * 10], [0, 360], { extrapolateRight: "extend" });
    const glowPulse = interpolate(frame % (fps * 3), [0, fps * 1.5, fps * 3], [0.4, 0.8, 0.4], { extrapolateRight: "clamp" });

    const splitText = (text: string, max = 25): string[] => {
        if (text.length <= max) return [text];
        const breaks = "\u3002\u3001\uff01\uff1f\uff09\u300d\u300f\u3011\u3009\u300b\u306e\u304c\u306f\u3092\u306b\u3067\u3082\u3078\u3068\u3084";
        let at = -1;
        for (let i = max; i >= max - 5 && i > 0; i--) {
            if (breaks.includes(text[i - 1])) { at = i; break; }
        }
        if (at < 0) at = max;
        if (text.length - at <= 3) return [text];
        return [text.slice(0, at), ...splitText(text.slice(at), max)];
    };

    const lines = splitText(consultationText);
    const totalTextDuration = durationInFrames - textStart;
    const framesPerLine = totalTextDuration / lines.length;

    // エリア高さから逆算してフォントサイズを決定（絶対にはみ出さない）
    // 利用可能高さ: 1080 - 130(top) - 70(bottom) - 70(padding上下) = 810px
    const availableHeight = 810;
    const lineHeightRatio = 1.5;
    const maxFontPerLine = availableHeight / (lines.length * lineHeightRatio);
    const textFontSize = Math.min(66, Math.max(30, Math.floor(maxFontPerLine)));
    const textLineHeight = textFontSize >= 58 ? 1.6 : textFontSize >= 46 ? 1.5 : 1.45;

    return (
        <AbsoluteFill style={{ backgroundColor: colors.bg }}>
            {/* 装飾: 浮遊光球 */}
            <div style={{ position: "absolute", top: `${30 + Math.sin(decorFloat * Math.PI / 180) * 8}%`, left: `${10 + Math.cos(decorFloat * Math.PI / 180) * 5}%`, width: 500, height: 500, borderRadius: "50%", backgroundColor: colors.decorColor, filter: "blur(60px)" }} />
            <div style={{ position: "absolute", top: `${55 + Math.sin((decorFloat + 120) * Math.PI / 180) * 6}%`, right: `${8 + Math.cos((decorFloat + 120) * Math.PI / 180) * 4}%`, width: 400, height: 400, borderRadius: "50%", backgroundColor: colors.decorColor, filter: "blur(50px)" }} />
            <div style={{ position: "absolute", top: -80, left: "25%", width: "50%", height: 250, backgroundColor: colors.decorColor, opacity: glowPulse, filter: "blur(50px)", borderRadius: "50%" }} />

            {/* 角装飾 */}
            <div style={{ position: "absolute", top: 10, left: 10, width: 70, height: 70, borderTop: `2px solid ${colors.borderColor}`, borderLeft: `2px solid ${colors.borderColor}`, opacity: 0.5 }} />
            <div style={{ position: "absolute", top: 10, right: 10, width: 70, height: 70, borderTop: `2px solid ${colors.borderColor}`, borderRight: `2px solid ${colors.borderColor}`, opacity: 0.5 }} />
            <div style={{ position: "absolute", bottom: 10, left: 10, width: 70, height: 70, borderBottom: `2px solid ${colors.borderColor}`, borderLeft: `2px solid ${colors.borderColor}`, opacity: 0.5 }} />
            <div style={{ position: "absolute", bottom: 10, right: 10, width: 70, height: 70, borderBottom: `2px solid ${colors.borderColor}`, borderRight: `2px solid ${colors.borderColor}`, opacity: 0.5 }} />

            {/* ジングル */}
            <Audio src={staticFile(jinglePath)} volume={0.5} />
            {audioPath && (<Sequence from={Math.round(fps * 1)}><Audio src={staticFile(audioPath)} volume={1.0} /></Sequence>)}

            {/* ヘッダー */}
            <div style={{ position: "absolute", top: 24, left: 30, right: 30, display: "flex", justifyContent: "space-between", alignItems: "flex-start", opacity: headerFadeIn }}>
                <div style={{ padding: "14px 36px", backgroundColor: colors.titleBg, borderBottom: `3px solid ${colors.titleBorder}`, borderRadius: 10, boxShadow: "0 4px 20px rgba(0,0,0,0.4)" }}>
                    <span style={{ fontFamily, fontSize: 56, fontWeight: 900, color: colors.titleColor, textShadow: `0 0 20px ${colors.accentColor}88, 2px 2px 6px rgba(0,0,0,0.7)`, letterSpacing: 2 }}>
                        {consultationTitle}
                    </span>
                </div>
                <div style={{ padding: "14px 36px", backgroundColor: colors.profileBg, borderBottom: `3px solid ${colors.titleBorder}`, borderRadius: 10, boxShadow: "0 4px 20px rgba(0,0,0,0.4)" }}>
                    <span style={{ fontFamily, fontSize: 38, fontWeight: 700, color: colors.keywordColor, textShadow: `0 0 12px ${colors.keywordColor}66, 2px 2px 4px rgba(0,0,0,0.7)` }}>
                        {consultantProfile}
                    </span>
                </div>
            </div>

            {/* 相談文エリア */}
            <div style={{ position: "absolute", top: 130, left: 30, right: 30, bottom: 70, border: `1px solid ${colors.borderColor}`, borderRadius: 16, backgroundColor: colors.boxBg, padding: "35px 40px", overflow: "hidden", opacity: textFadeIn, boxShadow: "0 8px 40px rgba(0,0,0,0.5)" }}>
                <div style={{ position: "absolute", top: 12, left: 12, right: 12, bottom: 12, border: `1px solid ${colors.borderColor}`, borderRadius: 10, opacity: 0.25, pointerEvents: "none" as const }} />
                {lines.map((lineText, i) => {
                    const lineStartFrame = textStart + i * framesPerLine;
                    const lineEndFrame = lineStartFrame + framesPerLine;
                    const lineProgress = Math.min(1, Math.max(0, (frame - lineStartFrame) / (lineEndFrame - lineStartFrame)));
                    const isActive = frame >= lineStartFrame;
                    const isPast = frame >= lineEndFrame;
                    return (
                        <div key={i} style={{
                            fontFamily, fontSize: textFontSize, fontWeight: 800, color: colors.textColor, lineHeight: textLineHeight, opacity: isActive ? 1 : 0.15, position: "relative" as const,
                            transform: `scale(${isActive && !isPast ? 1.01 : 1})`, transformOrigin: "left center",
                            textShadow: `0 0 ${isActive ? 20 : 5}px ${colors.accentColor}${isActive ? "88" : "22"}, 2px 2px 4px rgba(0,0,0,0.8), -1px -1px 0 ${colors.textStroke}${isActive ? "44" : "22"}, 1px -1px 0 ${colors.textStroke}${isActive ? "44" : "22"}, -1px 1px 0 ${colors.textStroke}${isActive ? "44" : "22"}, 1px 1px 0 ${colors.textStroke}${isActive ? "44" : "22"}`,
                        }}>
                            <span style={{ position: "relative" as const, display: "inline" as const }}>
                                {lineText}
                                {isActive && !isPast && (<span style={{ position: "absolute" as const, bottom: 6, left: 0, width: `${lineProgress * 100}%`, height: 5, backgroundColor: colors.accentColor, borderRadius: 3, boxShadow: `0 0 10px ${colors.accentColor}66` }} />)}
                                {isPast && (<span style={{ position: "absolute" as const, bottom: 6, left: 0, width: "100%", height: 4, backgroundColor: `${colors.accentColor}33`, borderRadius: 2 }} />)}
                            </span>
                        </div>
                    );
                })}
            </div>

            {/* カツミアイコン */}
            <div style={{ position: "absolute", bottom: 55, right: 55, opacity: headerFadeIn }}>
                <Img src={staticFile("katsumi_neutral.png")} style={{ width: 180, height: 180, borderRadius: "50%", border: `3px solid ${colors.accentColor}55`, boxShadow: `0 0 25px ${colors.accentColor}33, 0 4px 16px rgba(0,0,0,0.5)`, objectFit: "cover" as const }} />
            </div>
        </AbsoluteFill>
    );
};

export default NayamiOpening;
