/**
 * DynamicNewsVideo.tsx
 * カツミ・ヒロシみんなの声チャンネル動画コンポーネント v11 - チャート切替SE3種追加
 *
 * 機能:
 * - オープニング/控室スライド + ジングル
 * - キャラクター感情連動表示（3種: neutral, guts, yareyare）
 * - トピックポイント順次表示
 * - ティッカー（上部ニュース帯）
 * - フキダシアイコン（6種）
 */

import React from "react";
import {
    useCurrentFrame,
    useVideoConfig,
    AbsoluteFill,
    Audio,
    Sequence,
    Img,
    staticFile,
    interpolate,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansJP";
import { DataOverlay, ChartData } from "./DataOverlay";
import { HouseholdBudgetOverlay, HouseholdBudgetData } from "./HouseholdBudgetOverlay";
import { ChecklistOverlay, ChecklistData } from "./ChecklistOverlay";
import { ListenerLetterOverlay, ListenerLetterData } from "./ListenerLetterOverlay";

const { fontFamily } = loadFont();


// ==========================================
// 型定義
// ==========================================

interface ScriptLine {
    speaker: "カツミ" | "ヒロシ";
    text: string;
    emotion: string;
    startFrame: number;
    endFrame: number;
    section?: string;
}

interface DynamicNewsVideoProps {
    title: string;
    channelName: string;
    channelColor: string;
    source: string;
    script: ScriptLine[];
    audioPath: string;
    backgroundImage: string;
    keyPoints?: string[];
    ticker?: string[];
    slideDuration?: number;
    hikaeshitsuSlide?: string;
    hikaeshitsuJingle?: string;
    subtitleStyle?: "underline" | "bold" | "highlight";
    subtitleColor?: string;
    chartData?: { data: ChartData; triggerFrame: number }[];
    layoutPattern?: "documentary" | "checklist" | "radio";
    householdBudget?: HouseholdBudgetData;
    checklist?: ChecklistData;
    listenerLetter?: ListenerLetterData;
    jakuchoQuote?: string;
}


// ==========================================
// ユーティリティ関数
// ==========================================

/** 感情名からキャラクター画像ファイル名を取得（3種のみ：neutral, guts, yareyare） */
const getEmotionImage = (baseName: string, emotion: string): string => {
    const emotionMap: Record<string, string> = {
        // neutral: 通常の顔（デフォルト）
        neutral: "neutral", normal: "neutral", default: "neutral",
        smile: "neutral", calm: "neutral",
        // guts: いいですね！やりましたね！すごい！期待！ワクワク！最高！
        happy: "guts", excited: "guts", guts: "guts",
        surprised: "guts", laugh: "guts", bakusho: "guts",
        idea: "guts", hirameki: "guts",
        // yareyare: いまいち、やれやれ、全然、教えてくれればいいのに、わかりづらい、なにやってんだか、これだから政治家は、あてにならない、庶民の気持ちわかってない
        concerned: "yareyare", tired: "yareyare", yareyare: "yareyare",
        sad: "yareyare", fuseru: "yareyare", doyon: "yareyare",
        question: "yareyare", thinking: "yareyare", henken: "yareyare",
        shocked: "yareyare", aogu: "yareyare", sukashi: "yareyare",
        imaichi: "yareyare", akire: "yareyare", fuman: "yareyare",
        ganakkari: "yareyare", tameiki: "yareyare", uso: "yareyare",
    };
    const emotionKey = emotionMap[emotion?.toLowerCase() || "neutral"] || "neutral";
    return `${baseName}_${emotionKey}.png`;
};

/** 感情名から吹き出しアイコン画像を取得（6種のみ） */
const getEmotionBubbleImage = (emotion: string): string | null => {
    const bubbleMap: Record<string, string> = {
        // gimon: 疑問？なんで？
        question: "gimon.png", thinking: "gimon.png",
        // hirameki: わかった！そうか！
        idea: "hirameki.png", hirameki: "hirameki.png",
        // iine/suki: いいですね！おすすめ！最高！
        happy: "iine.png", excited: "iine.png", guts: "suki.png",
        // moyamoya: すっきりしない、お役所仕事、イマイチ、やれやれ、なにやってんだか、これだから政治家は、あてにならない、庶民の気持ちわかってない
        concerned: "moyamoya.png", tired: "moyamoya.png", yareyare: "moyamoya.png",
        imaichi: "moyamoya.png", akire: "moyamoya.png", fuman: "moyamoya.png",
        ganakkari: "moyamoya.png", tameiki: "moyamoya.png", uso: "moyamoya.png",
        // odoroki: びっくり！そうなんですか！
        surprised: "odoroki.png", shocked: "odoroki.png",
    };
    return bubbleMap[emotion?.toLowerCase() || ""] || null;
};



// ==========================================
// サブコンポーネント
// ==========================================

/** スライド表示（ジングル付き） */
const SlideWithJingle: React.FC<{
    slideImage: string;
    jinglePath: string;
    durationFrames: number;
    slideText?: string;
    channelName?: string;
    channelColor?: string;
}> = ({ slideImage, jinglePath, durationFrames, slideText, channelName, channelColor = "#1a237e" }) => {
    const frame = useCurrentFrame();
    // フェードアウト（最後10フレーム）
    const fadeOut = Math.min(1, (durationFrames - frame) / 10);
    // タイトル: 奥から手前に微ズーム（控えめ、0.85→1.0）
    const titleProgress = Math.min(1, frame / 15);
    const titleScale = 0.85 + titleProgress * 0.15; // 0.85→1.0
    const titleOpacity = Math.min(1, frame / 8);
    // 速報バッジ: 少し遅れて微ズーム
    const subProgress = Math.min(1, Math.max(0, (frame - 4) / 12));
    const subScale = 0.9 + subProgress * 0.1; // 0.9→1.0
    const subOpacity = Math.min(1, Math.max(0, (frame - 4) / 6));
    // 微振動（存在感）
    const pulse = 1 + Math.sin(frame * 0.15) * 0.005;

    return (
        <AbsoluteFill style={{ opacity: fadeOut, zIndex: 1000 }}>
            <Img
                src={staticFile(slideImage)}
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
            {/* 暗いオーバーレイ */}
            <div style={{
                position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
                background: "linear-gradient(180deg, rgba(0,0,0,0.3) 0%, rgba(0,0,0,0.6) 100%)",
            }} />
            {/* マスコットキャラクター（速報バッジの左隣に表示） */}
            <Img
                src={staticFile("mascot.png")}
                style={{
                    position: "absolute", top: "2%", left: 20,
                    height: 200, opacity: titleOpacity,
                    filter: "drop-shadow(4px 4px 8px rgba(0,0,0,0.6))",
                    zIndex: 1001,
                }}
            />
            {slideText && (
                <>
                    {/* 赤帯タイトル */}
                    <div style={{
                        position: "absolute", top: "20%", left: 0, right: 0, bottom: "12%",
                        display: "flex", justifyContent: "center", alignItems: "center",
                        transform: `scale(${titleScale * pulse})`,
                        opacity: titleOpacity,
                        padding: "0 8%",
                        boxSizing: "border-box",
                    }}>
                        <div style={{
                            fontFamily, fontSize: slideText.length <= 10 ? 200 : slideText.length <= 15 ? 160 : slideText.length <= 20 ? 130 : slideText.length <= 25 ? 110 : slideText.length <= 30 ? 95 : slideText.length <= 40 ? 80 : 68, fontWeight: 900,
                            color: "#ffffff", letterSpacing: 2,
                            textShadow: "4px 4px 0px rgba(0,0,0,1), 2px 2px 12px rgba(0,0,0,0.8)",
                            background: `linear-gradient(135deg, ${channelColor} 0%, ${channelColor}dd 50%, ${channelColor} 100%)`,
                            padding: "24px 40px", borderRadius: 8,
                            border: "4px solid #ffffff",
                            boxShadow: "0 8px 30px rgba(0,0,0,0.7), inset 0 2px 0 rgba(255,255,255,0.2)",
                            maxWidth: "100%", textAlign: "center",
                            lineHeight: 1.3,
                            boxSizing: "border-box",
                            overflow: "hidden",
                            wordBreak: "keep-all",
                            overflowWrap: "break-word",
                        }}>
                            {slideText}
                        </div>
                    </div>
                    {/* OPバッジ（タイトル連動の感情訴求文言） */}
                    <div style={{
                        position: "absolute", top: "2%", left: 240,
                        transform: `scale(${subScale})`,
                        opacity: subOpacity,
                    }}>
                        <div style={{
                            fontFamily, fontSize: 72, fontWeight: 900,
                            color: "#1a237e", letterSpacing: 8,
                            background: "linear-gradient(135deg, #ffffff 0%, #e8eaf6 100%)",
                            padding: "12px 50px", borderRadius: 4,
                            border: "3px solid #c5cae9",
                            boxShadow: "0 4px 15px rgba(0,0,0,0.5)",
                        }}>
                            {(() => {
                                const t = slideText || "";
                                if (t.includes("期限") || t.includes("締切") || t.includes("まで")) return "期限迫る！";
                                if (t.includes("申請") || t.includes("受給") || t.includes("もらえ")) return "もうもらった？";
                                if (t.includes("損") || t.includes("負担") || t.includes("減額")) return "損しないで！";
                                if (t.includes("改正") || t.includes("変更") || t.includes("新")) return "知ってた？";
                                if (t.includes("廃止") || t.includes("縮小") || t.includes("削減")) return "これマジ？";
                                if (t.includes("増額") || t.includes("拡充") || t.includes("引き上げ")) return "要チェック！";
                                const badges = ["知ってた？", "損しないで！", "要チェック！", "見逃し厳禁！", "今すぐ確認！"];
                                return badges[t.length % badges.length];
                            })()}
                        </div>
                    </div>
                </>
            )}
            <Audio src={staticFile(jinglePath)} volume={0.3} />
        </AbsoluteFill>
    );
};

/** ティッカー（上部ニュース帯） */
const Ticker: React.FC<{ durationInFrames: number; texts?: string[] }> = ({ durationInFrames, texts }) => {
    const frame = useCurrentFrame();
    const { width } = useVideoConfig();

    const tickerTexts = texts && texts.length > 0 ? texts : [
        "カツミとヒロシの本音ニューストーク",
    ];
    const tickerText = "　　　　　　　　" + tickerTexts.join("　　　　　　　　") + "　　　　　　　　";
    const textWidth = tickerText.length * 56;
    const offset = (frame * 1.2) % (textWidth + width);

    return (
        <div style={{
            position: "absolute", bottom: 0, left: 0, right: 0, height: 80,
            backgroundColor: "rgba(0, 0, 0, 0.95)", overflow: "hidden",
            display: "flex", alignItems: "center", paddingBottom: 10,
            zIndex: 100,
            clipPath: "inset(0)",
        }}>
            <div style={{
                position: "absolute", left: width - offset, whiteSpace: "nowrap",
                fontFamily, fontSize: 48, fontWeight: "bold", color: "#ffffff",
            }}>
                {tickerText}
            </div>
        </div>
    );
};



/** キャラクター表示（字幕エリア内アイコン） */
const Character: React.FC<{
    baseName: string;
    name: string;
    position: "left" | "right";
    isActive: boolean;
    emotion: string;
}> = ({ baseName, name, position, isActive, emotion }) => {
    const frame = useCurrentFrame();
    const bounce = isActive ? Math.sin(frame * 0.5) * 3 : 0;
    const imagePath = getEmotionImage(baseName, emotion);

    return (
        <div style={{
            position: "absolute", bottom: 85, [position]: 5,
            transform: `translateY(${bounce}px)`, textAlign: "center",
            zIndex: 50,
        }}>
            <Img
                src={staticFile(imagePath)}
                style={{
                    height: 140,
                    filter: isActive ? "none" : "brightness(0.75)",
                    borderRadius: 6,
                }}
            />
        </div>
    );
};

/** 字幕演出コンポーネント（3パターン対応） */
const SubtitleLine: React.FC<{
    line: ScriptLine;
    isHikaeshitsu: boolean;
    barY: number;
    barHeight: number;
    style: "underline" | "bold" | "highlight";
    highlightColor?: string;
}> = ({ line, isHikaeshitsu, barY, barHeight, style, highlightColor }) => {
    const frame = useCurrentFrame();
    // 行内での進行率（0→1）
    const lineProgress = Math.min(1, Math.max(0, (frame - line.startFrame) / (line.endFrame - line.startFrame)));
    const baseColor = isHikaeshitsu ? "#ffff00" : "#ffffff";
    const fadeIn = interpolate(frame - line.startFrame, [0, 5], [0, 1], { extrapolateRight: "clamp", extrapolateLeft: "clamp" });

    if (style === "underline") {
        // パターンA: 下線が進む
        return (
            <div style={{
                opacity: fadeIn,
                position: "absolute", top: barY + 8, left: 220, right: 170,
                fontFamily, fontSize: line.text.length > 30 ? 72 : line.text.length > 20 ? 82 : 95, fontWeight: "bold",
                color: baseColor,
                textShadow: "4px 4px 10px rgba(0,0,0,0.95)", textAlign: "left",
                lineHeight: 1.15, maxHeight: barHeight - 100,
                wordBreak: "keep-all" as const,
                overflowWrap: "break-word" as const,
            }}>
                <span style={{ position: "relative", display: "inline" }}>
                    {line.text}
                    <span style={{
                        position: "absolute", bottom: -2, left: 0,
                        width: `${lineProgress * 100}%`, height: 8,
                        backgroundColor: isHikaeshitsu ? "#ff9900" : "#ff6b6b",
                        borderRadius: 4,
                        transition: "width 0.05s linear",
                    }} />
                </span>
            </div>
        );
    }

    if (style === "bold") {
        // パターンB: フェードイン＋微拡大で文字が「浮き出る」演出
        const boldProgress = Math.min(1, lineProgress * 3);
        const opacity = 0.4 + boldProgress * 0.6;
        const scale = 0.97 + boldProgress * 0.03;
        return (
            <div style={{
                opacity: fadeIn * (0.4 + boldProgress * 0.6),
                position: "absolute", top: barY + 8, left: 220, right: 170,
                fontFamily, fontSize: line.text.length > 30 ? 72 : line.text.length > 20 ? 82 : 95, fontWeight: 900,
                color: baseColor,
                textShadow: "4px 4px 10px rgba(0,0,0,0.95)",
                textAlign: "left",
                lineHeight: 1.15, maxHeight: barHeight - 100,
                wordBreak: "keep-all" as const,
                overflowWrap: "break-word" as const,
                transform: `scale(${scale})`,
            }}>
                {line.text}
            </div>
        );
    }

    // パターンC: 背景色が左から右にスライド（行ごとにハイライト）
    const hlColor = highlightColor || "rgba(220,140,30,0.5)";

    // 枠幅ベースのsplitText（1580px基準、85%まで絶対1行、90%超えたら文節で改行）
    const SUBTITLE_AREA_WIDTH = 1580;
    const subtitleFontSize = line.text.length > 30 ? 72 : line.text.length > 20 ? 82 : 95;
    const splitText = (text: string, fontSize: number): string[] => {
        const maxChars = Math.floor(SUBTITLE_AREA_WIDTH * 0.90 / fontSize);
        const minChars = Math.floor(SUBTITLE_AREA_WIDTH * 0.85 / fontSize);
        if (text.length <= maxChars) return [text];
        const breakAfter = "。、！？）」』】〉》のがはをにでもへとやけどてからまでよりならばし";
        let at = -1;
        for (let i = maxChars; i >= minChars && i > 0; i--) {
            if (breakAfter.includes(text[i - 1])) { at = i; break; }
        }
        if (at < 0) at = maxChars;
        if (text.length - at <= 3) return [text];
        return [text.slice(0, at), ...splitText(text.slice(at), fontSize)];
    };

    const lines = splitText(line.text, subtitleFontSize);
    const totalLines = lines.length;

    return (
        <div style={{
            opacity: fadeIn,
            position: "absolute", top: barY + 8, left: 220, right: 170,
            fontFamily, fontSize: subtitleFontSize, fontWeight: "bold",
            color: baseColor,
            textShadow: "4px 4px 10px rgba(0,0,0,0.95)", textAlign: "left",
            lineHeight: 1.15, maxHeight: barHeight - 100,
            wordBreak: "keep-all" as const,
            overflowWrap: "break-word" as const,
        }}>
            {lines.map((lineText, i) => {
                const lineStart = i / totalLines;
                const lineEnd = (i + 1) / totalLines;
                const perLineProgress = Math.min(1, Math.max(0,
                    (lineProgress - lineStart) / (lineEnd - lineStart)
                ));
                return (
                    <React.Fragment key={i}>
                        <span style={{
                            position: "relative", display: "inline",
                            padding: "4px 10px", borderRadius: 6,
                            background: `linear-gradient(to bottom, transparent 55%, ${hlColor} 55%)`,
                            backgroundSize: `${perLineProgress * 100}% 100%`,
                            backgroundRepeat: "no-repeat",
                            wordBreak: "keep-all" as const,
                            lineBreak: "strict",
                        }}>
                            {lineText}
                        </span>
                        {i < lines.length - 1 && <br />}
                    </React.Fragment>
                );
            })}
        </div>
    );
};


// ==========================================
// メインコンポーネント
// ==========================================

export const DynamicNewsVideo: React.FC<DynamicNewsVideoProps> = ({
    title,
    channelName,
    channelColor,
    source,
    script,
    audioPath,
    backgroundImage,
    keyPoints,
    slideDuration: rawSlideDuration = 168,
    hikaeshitsuSlide,
    hikaeshitsuJingle,
    subtitleStyle = "highlight",
    subtitleColor,
    chartData,
    layoutPattern,
    householdBudget,
    checklist,
    listenerLetter,
    jakuchoQuote,
}) => {
    const frame = useCurrentFrame();
    const { durationInFrames, height } = useVideoConfig();

    // 瀬戸内寂聴名言がある場合はOPスライド表示、なければスキップ
    const hasJakuchoQuote = !!jakuchoQuote;
    const slideDuration = hasJakuchoQuote ? rawSlideDuration : 0;

    const currentLine = script.find(line => frame >= line.startFrame && frame < line.endFrame);
    const isEndingSection = currentLine?.section === "ending" || currentLine?.section === "hikaeshitsu" || currentLine?.section === "hikaeshitsu_jingle";
    const isHikaeshitsu = currentLine?.section === "hikaeshitsu" || currentLine?.section === "hikaeshitsu_jingle";

    // チャート表示中かどうか（ティッカー非表示用）
    const isChartVisible = (() => {
        if (!chartData) return false;
        for (let ci = chartData.length - 1; ci >= 0; ci--) {
            if (frame >= chartData[ci].triggerFrame) {
                const nt = ci < chartData.length - 1 ? chartData[ci + 1].triggerFrame : Infinity;
                return frame < nt;
            }
        }
        return false;
    })();

    const barHeight = height * 0.40;
    const barY = height - barHeight;

    // Ken Burns: 背景画像の微ズーム
    const kenBurnsScale = interpolate(frame, [0, durationInFrames], [1.0, 1.08], {
        extrapolateRight: "clamp",
    });

    const hikaeshitsuStartFrame = script.find(l => l.section === "hikaeshitsu")?.startFrame || null;

    return (
        <AbsoluteFill>
            {/* 背景（OPスライド後に表示、控室時は黒背景） */}
            {frame >= slideDuration && !isHikaeshitsu && (
                <Img
                    src={staticFile(backgroundImage)}
                    style={{ width: "100%", height: "115%", marginTop: "-7.5%", objectFit: "cover", transform: `scale(${kenBurnsScale})` }}
                />
            )}
            {isHikaeshitsu && (
                <div style={{ width: "100%", height: "100%", backgroundColor: "#000000" }} />
            )}

            {/* 音声（slideDuration後から再生開始 = クイズintroとの音声被り防止） */}
            <Sequence from={slideDuration}>
                <Audio src={staticFile(audioPath)} />
                <Audio src={staticFile("main_bgm.mp3")} volume={0.1} loop />
            </Sequence>

            {/* ===== 冒頭: 瀬戸内寂聴名言スライド ===== */}
            {slideDuration > 0 && hasJakuchoQuote && (() => {
                const quoteText = jakuchoQuote || "いくつになっても\n恋愛感情がなくなったわけでは\nないんです。\nただ、その表現の仕方が\n変わってきただけ。";

                // アニメーション: 1.今日の一言 → 2.名言テキスト → 3.寂聴さん画像が後から登場
                const subtitleOpacity = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
                const textOpacity = interpolate(frame, [20, 45], [0, 1], { extrapolateRight: "clamp" });
                const iconOpacity = interpolate(frame, [50, 75], [0, 1], { extrapolateRight: "clamp" });
                const iconScale = interpolate(frame, [50, 75], [0.3, 1], { extrapolateRight: "clamp" });
                const iconTranslateX = interpolate(frame, [50, 75], [-120, 0], { extrapolateRight: "clamp" });
                const iconGlow = interpolate(frame, [60, 80], [0, 1], { extrapolateRight: "clamp" });
                const fadeOut = interpolate(frame, [slideDuration - 15, slideDuration], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

                return (
                    <Sequence from={0} durationInFrames={slideDuration}>
                        <AbsoluteFill style={{ backgroundColor: "#0a0a0a", zIndex: 1000, opacity: fadeOut }}>
                            <Audio src={staticFile("main_jingle.mp3")} volume={0.3} />

                            {/* 上部: 瀬戸内寂聴アイコン(左) + 名言テキスト(右) */}
                            <div style={{
                                position: "absolute", top: 60, left: 60, right: 60, bottom: 320,
                                display: "flex", flexDirection: "row", alignItems: "center",
                                gap: 60,
                            }}>
                                {/* 左: 丸アイコン（後から登場） */}
                                <div style={{
                                    opacity: iconOpacity,
                                    transform: `scale(${iconScale}) translateX(${iconTranslateX}px)`,
                                    flexShrink: 0,
                                    filter: `drop-shadow(0 0 ${iconGlow * 30}px rgba(200, 168, 78, ${iconGlow * 0.8}))`,
                                }}>
                                    <Img
                                        src={staticFile("setouchi_jakucho.png")}
                                        style={{
                                            width: 480, height: 480, borderRadius: "50%",
                                            objectFit: "cover",
                                            border: "4px solid #C8A84E",
                                            boxShadow: "0 0 40px rgba(200, 168, 78, 0.4)",
                                        }}
                                    />
                                    <div style={{
                                        textAlign: "center", marginTop: 16,
                                        fontFamily, fontSize: 36, fontWeight: 700,
                                        color: "#C8A84E",
                                    }}>
                                        瀬戸内寂聴
                                    </div>
                                </div>

                                {/* 右: 名言テキスト */}
                                <div style={{
                                    flex: 1, opacity: textOpacity,
                                    backgroundColor: "rgba(30, 30, 30, 0.9)",
                                    borderRadius: 16, padding: "40px 48px",
                                    border: "2px solid #C8A84E",
                                    boxShadow: "0 4px 20px rgba(0,0,0,0.5)",
                                }}>
                                    <div style={{
                                        fontFamily, fontSize: 28, fontWeight: 600,
                                        color: "#C8A84E", marginBottom: 24,
                                    }}>
                                        瀬戸内寂聴の言葉
                                    </div>
                                    <div style={{
                                        fontFamily, fontSize: 52, fontWeight: 700,
                                        color: "#ffffff", lineHeight: 1.6,
                                        whiteSpace: "pre-line",
                                    }}>
                                        {quoteText}
                                    </div>
                                    <div style={{
                                        textAlign: "right", marginTop: 24,
                                        fontFamily, fontSize: 30, fontWeight: 600,
                                        color: "#C8A84E",
                                    }}>
                                        ——瀬戸内寂聴
                                    </div>
                                </div>
                            </div>

                            {/* 下部: 「今日の一言」テキスト（アイコンなし） */}
                            <div style={{
                                position: "absolute", bottom: 0, left: 0, right: 0, height: 280,
                                backgroundColor: "rgba(0,0,0,0.85)",
                                display: "flex", alignItems: "center", justifyContent: "center",
                                padding: "0 60px",
                                opacity: subtitleOpacity,
                            }}>
                                <div style={{
                                    fontFamily, fontSize: 128, fontWeight: 900,
                                    color: "#FFD700",
                                    textShadow: "4px 4px 12px rgba(0,0,0,0.9)",
                                    lineHeight: 1.3,
                                    textAlign: "center",
                                }}>
                                    今日の一言
                                </div>
                            </div>
                        </AbsoluteFill>
                    </Sequence>
                );
            })()}

            {/* 本編→控室のフェードアウト（控室開始の132+60=192フレーム前から黒にフェードアウト） */}
            {/* フェードアウト60F → 完全黒画面72F(3秒余韻) → 「控室にて」テキスト表示120F */}
            {hikaeshitsuStartFrame && frame >= hikaeshitsuStartFrame - 192 && frame < hikaeshitsuStartFrame - 132 && (
                <div style={{
                    position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
                    backgroundColor: "#000000",
                    opacity: Math.min(1, (frame - (hikaeshitsuStartFrame - 192)) / 60),
                    zIndex: 999,
                }} />
            )}

            {/* 完全黒画面（3秒の余韻・無音・無テキスト） */}
            {hikaeshitsuStartFrame && frame >= hikaeshitsuStartFrame - 132 && frame < hikaeshitsuStartFrame - 60 && (
                <div style={{
                    position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
                    backgroundColor: "#000000",
                    zIndex: 999,
                }} />
            )}

            {/* 控え室開始前の「控室にて」テキスト表示 */}
            {hikaeshitsuStartFrame && frame >= hikaeshitsuStartFrame - 60 && frame < hikaeshitsuStartFrame + 60 && (() => {
                const elapsed = frame - (hikaeshitsuStartFrame - 60);
                const textOpacity = elapsed < 30 ? 0 : Math.min(1, (elapsed - 30) / 15);
                return (
                    <AbsoluteFill style={{ backgroundColor: "#000000", zIndex: 1000, display: "flex", justifyContent: "center", alignItems: "center" }}>
                        <div style={{
                            fontFamily, fontSize: 120, fontWeight: "bold",
                            color: "#ffffff", textShadow: "4px 4px 20px rgba(0,0,0,0.9)",
                            textAlign: "center", lineHeight: 1.2,
                            opacity: textOpacity,
                            letterSpacing: 24,
                        }}>
                            控 室 に て
                        </div>
                    </AbsoluteFill>
                );
            })()}

            {/* ティッカー（本編のみ表示、控室・チャート表示中は非表示） */}
            {frame >= slideDuration && !isEndingSection && !isChartVisible && <Ticker durationInFrames={durationInFrames} texts={[title, ...(keyPoints || [])]} />}

            {/* トピックポイント: 削除（チャート・音声とのタイミング同期が不可能なため
               間違った情報表示より非表示が正解） */}





            {/* 出典（ニュースソース）透過バーの上にレイヤー、右端寄せ白文字 */}
            {/* 独自取材の場合は出典を表示しない */}
            {!isHikaeshitsu && source && source !== "独自取材" && (
                <div style={{
                    position: "absolute", top: barY - 2, right: 20,
                    fontFamily, fontSize: 28, fontWeight: "bold", color: "#ffffff",
                    textShadow: "2px 2px 6px rgba(0,0,0,0.8)",
                    zIndex: 105,
                }}>
                    出典：{source}
                </div>
            )}

            {/* 透過バー */}
            <div style={{
                position: "absolute", left: 0, right: 0, top: barY, height: barHeight,
                backgroundColor: "rgba(0, 0, 0, 0.75)",
            }} />

            {/* チャートデータ表示: 左チョーク風画像 + 右チャート (画面上部を左右50:50分割、余白なし) */}
            {chartData && (() => {
                let activeIndex = -1;
                for (let i = chartData.length - 1; i >= 0; i--) {
                    if (frame >= chartData[i].triggerFrame) {
                        activeIndex = i;
                        break;
                    }
                }
                if (activeIndex === -1) return null;
                const cd = chartData[activeIndex];
                const nextTrigger = activeIndex < chartData.length - 1
                    ? chartData[activeIndex + 1].triggerFrame
                    : Infinity;
                if (frame >= nextTrigger) return null;

                // フラッシュ防止: opacityフェードではなくスライドインで切替
                const slideIn = interpolate(frame - cd.triggerFrame, [0, 12], [40, 0], { extrapolateRight: "clamp" });
                const fadeIn = interpolate(frame - cd.triggerFrame, [0, 8], [0, 1], { extrapolateRight: "clamp" });
                const panelHeight = barY - 4; // 透過バーの上端まで

                return (
                    <>
                        {/* ===== 左パネル: チョーク風画像（キャプション削除=DataOverlayと重複防止） ===== */}
                        <div style={{
                            position: "absolute", top: 0, left: 0,
                            width: "50%", height: panelHeight,
                            backgroundColor: "#000000",
                            zIndex: 100,
                            display: "flex", flexDirection: "column",
                            opacity: fadeIn,
                            transform: `translateX(${-slideIn}px)`,
                            overflow: "hidden",
                            boxSizing: "border-box",
                        }}>
                            {/* チョーク画像 */}
                            <div style={{
                                flex: 1, width: "100%",
                                display: "flex", justifyContent: "center", alignItems: "center",
                                overflow: "hidden",
                            }}>
                                <Img
                                    src={staticFile("chalk_illustration.png")}
                                    style={{
                                        width: "100%", height: "100%", objectFit: "cover",
                                    }}
                                />
                            </div>
                            {/* ラベルはDataOverlay側に表示するため、左パネルでは重複削除 */}
                        </div>

                        {/* ===== 右パネル: チャート (95%使用、余白5%以内) ===== */}
                        <DataOverlay
                            key={activeIndex}
                            chartData={cd.data}
                            startFrame={cd.triggerFrame}
                            channelColor={channelColor}
                            compact
                            panelHeight={panelHeight}
                        />
                    </>
                );
            })()}

            {/* レイアウトパターン別オーバーレイ */}
            {layoutPattern === "documentary" && householdBudget && (
                <HouseholdBudgetOverlay
                    data={householdBudget}
                    startFrame={slideDuration + 48}
                    channelColor={channelColor}
                />
            )}
            {layoutPattern === "checklist" && checklist && (
                <ChecklistOverlay
                    data={checklist}
                    channelColor={channelColor}
                />
            )}
            {layoutPattern === "radio" && listenerLetter && (
                <ListenerLetterOverlay
                    data={listenerLetter}
                    startFrame={slideDuration + 48}
                    channelColor={channelColor}
                />
            )}

            {/* チャート切替SE（メイン音声に被せる・字幕同期に影響なし） */}
            {chartData && chartData.map((cd, i) => {
                // ガード: triggerFrameが動画の範囲外ならスキップ
                if (cd.triggerFrame >= durationInFrames || cd.triggerFrame < 0) return null;
                // ガード: 前のSEとの間隔が60フレーム(2秒)未満なら重複防止でスキップ
                if (i > 0 && cd.triggerFrame - chartData[i - 1].triggerFrame < 60) return null;
                // SE再生可能フレーム数(動画末端を超えない)
                const seDuration = Math.min(90, durationInFrames - cd.triggerFrame);
                if (seDuration <= 0) return null;

                const label = (cd.data?.label || "");
                const MONEY_KEYWORDS = [
                    "合計", "総額", "金額", "万円", "億", "兆", "費用",
                    "支出", "収入", "給付", "受給", "年金額", "手取り",
                    "月額", "年額", "平均", "中央値", "世帯", "貯蓄",
                ];
                const NEGATIVE_KEYWORDS = [
                    "減", "少な", "足りな", "不足", "下が", "苦し", "厳し",
                    "いまいち", "お役所", "政治家", "金持ち", "格差", "負担",
                    "不安", "心配", "大変", "困", "赤字", "マイナス", "低",
                    "悪", "問題", "危", "高齢", "老後", "介護",
                ];
                const isMoney = MONEY_KEYWORDS.some(kw => label.includes(kw));
                const isNegative = NEGATIVE_KEYWORDS.some(kw => label.includes(kw));
                const jingleFile = isMoney ? "chart_money.mp3" : isNegative ? "chart_negative.mp3" : "chart_jingle.mp3";
                return (
                    <Sequence key={`chart-se-${i}`} from={cd.triggerFrame} durationInFrames={seDuration}>
                        <Audio
                            src={staticFile(jingleFile)}
                            volume={0.3}
                        />
                    </Sequence>
                );
            })}

            {/* プログレスバー */}
            <div style={{
                position: "absolute", bottom: 0, left: 0, right: 0, height: 6,
                backgroundColor: "rgba(0,0,0,0.3)", zIndex: 101,
            }}>
                <div style={{
                    height: "100%",
                    width: `${(frame / durationInFrames) * 100}%`,
                    backgroundColor: channelColor,
                }} />
            </div>

            {/* キャラクター（控室時は非表示） */}
            {!isHikaeshitsu && (
                <>
                    <Character
                        baseName="katsumi"
                        name="カツミ"
                        position="left"
                        isActive={currentLine?.speaker === "カツミ"}
                        emotion={currentLine?.speaker === "カツミ" ? currentLine?.emotion || "neutral" : "neutral"}
                    />
                    <Character
                        baseName="hiroshi"
                        name="ヒロシ"
                        position="right"
                        isActive={currentLine?.speaker === "ヒロシ"}
                        emotion={currentLine?.speaker === "ヒロシ" ? currentLine?.emotion || "neutral" : "neutral"}
                    />
                </>
            )}

            {/* 字幕（3パターン演出対応・控室時は黄色） */}
            {currentLine && (
                <SubtitleLine
                    line={currentLine}
                    isHikaeshitsu={isHikaeshitsu}
                    barY={barY}
                    barHeight={barHeight}
                    style={subtitleStyle}
                    highlightColor={subtitleColor}
                />
            )}

            {/* 吹き出しアイコン（キャラの上に表示） */}
            {currentLine && getEmotionBubbleImage(currentLine.emotion) && !isHikaeshitsu && (
                <>
                    {currentLine.speaker === "カツミ" && (
                        <div style={{ position: "absolute", bottom: 230, left: 30, width: 100, height: 100, zIndex: 51 }}>
                            <Img
                                src={staticFile(`emotions/${getEmotionBubbleImage(currentLine.emotion)}`)}
                                style={{ width: "100%", height: "100%", objectFit: "contain" }}
                            />
                        </div>
                    )}
                    {currentLine.speaker === "ヒロシ" && (
                        <div style={{ position: "absolute", bottom: 230, right: 30, width: 100, height: 100, zIndex: 51 }}>
                            <Img
                                src={staticFile(`emotions/${getEmotionBubbleImage(currentLine.emotion)}`)}
                                style={{ width: "100%", height: "100%", objectFit: "contain" }}
                            />
                        </div>
                    )}
                </>
            )}
        </AbsoluteFill>
    );
};

export default DynamicNewsVideo;
