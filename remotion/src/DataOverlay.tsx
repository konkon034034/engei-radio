/**
 * DataOverlay.tsx
 * 数値データをアニメーションチャートとして表示するコンポーネント
 * 
 * 8タイプ対応:
 * - bar: 棒グラフ（横バーが伸びる）
 * - number: 数値カウントアップ
 * - pie: 円グラフ（扇型が回転しながら埋まる）
 * - donut: ドーナツチャート（中央に大きな数値）
 * - compare: 横型比較バー（賛成/反対）
 * - flipcard: フリップカード（数値ボード回転）
 * - ranking: ランキングリスト（項目がスライドイン）
 * - poll: アンケート／世論調査（横バー＋%表示）
 */
import React from "react";
import {
    useCurrentFrame,
    interpolate,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansJP";

const { fontFamily } = loadFont();

export interface ChartData {
    type: "bar" | "number" | "pie" | "donut" | "compare" | "flipcard" | "ranking" | "poll";
    label: string;
    value: number;
    unit: string;
    maxValue?: number;
    // compare用
    compareLabel?: string;
    compareValue?: number;
    // ranking用
    items?: { label: string; value: number }[];
    // ビフォーアフター・補足情報
    subtitle?: string;
    negative?: boolean;
}

/** ラベル内容からセンチメント判定→チャート色を返す */
const getSentimentColor = (label: string, channelColor: string): string => {
    const t = label || "";
    // ポジティブ（緑系）: 増額、拡充、支給、もらえる、引き上げ、改善、増加
    if (/増額|拡充|支給|もらえ|引き上げ|改善|増加|上昇|プラス|給付|受給|対象拡大|無料/.test(t)) return "#4CAF50";
    // ネガティブ（赤系）: 減額、廃止、削減、負担、損、値上げ、縮小、打ち切り
    if (/減額|廃止|削減|負担|損|値上[がげ]|縮小|打ち切|引き下げ|マイナス|不足|赤字/.test(t)) return "#e74c3c";
    // ニュートラル（青系）: その他
    return "#42A5F5";
};

export const DataOverlay: React.FC<{
    chartData: ChartData;
    startFrame: number;
    channelColor: string;
    compact?: boolean;
}> = ({ chartData, startFrame, channelColor, compact }) => {
    const frame = useCurrentFrame();
    const elapsed = frame - startFrame;

    // 60フレーム（2.5秒）かけてアニメーション
    const animProgress = interpolate(elapsed, [0, 60], [0, 1], {
        extrapolateRight: "clamp",
        extrapolateLeft: "clamp",
    });

    // フェードイン（最初の10フレーム）
    const opacity = interpolate(elapsed, [0, 10], [0, 1], {
        extrapolateRight: "clamp",
        extrapolateLeft: "clamp",
    });

    // フェードアウトはDynamicNewsVideo側で制御（次のtriggerFrameで切り替え）
    const finalOpacity = opacity;

    // ラベルからセンチメント色を取得
    const sentimentColor = getSentimentColor(chartData.label, channelColor);

    // 共通コンテナスタイル（キャラクター間の黒板パネル）
    // カツミ(left:0, 幅約200px) と ヒロシ(right:0, 幅約200px) にかぶらない領域
    // キャラ実測: カツミ右端=280px, ヒロシ左端=1640px → 使用可能エリア=1360px
    // compact時: 黄金比38.2:61.8 → 左520px, 右840px
    // non-compact時: 使用可能エリアの中央に配置（左右均等マージン）
    const containerStyle: React.CSSProperties = {
        position: "absolute",
        top: 10,
        left: compact ? 280 : 310,
        width: compact ? 520 : 1300,
        height: compact ? 640 : 640,
        padding: compact ? "20px 18px" : "12px 16px",
        backgroundColor: "rgba(0, 0, 0, 0.85)",
        borderRadius: 16,
        opacity: finalOpacity,
        borderLeft: `6px solid ${sentimentColor}`,
        zIndex: 100,
        boxSizing: "border-box",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        justifyContent: compact ? "center" : "space-between",
        alignItems: compact ? "center" : "stretch",
    };

    // ラベルの長さに応じてフォントサイズを自動調整（コンテナ1320x640に収まる範囲）
    const labelFontSize = compact
        ? (chartData.label.length <= 6 ? 56 : chartData.label.length <= 10 ? 46 : 38)
        : (chartData.label.length <= 6 ? 100
            : chartData.label.length <= 10 ? 80
                : chartData.label.length <= 14 ? 68
                    : chartData.label.length <= 18 ? 60
                        : chartData.label.length <= 24 ? 52
                            : 44);

    const labelStyle: React.CSSProperties = {
        fontFamily, fontSize: labelFontSize, fontWeight: 900,
        color: "#ffffff", marginBottom: compact ? 12 : 4,
        lineHeight: 1.15, wordBreak: "keep-all", overflowWrap: "break-word",
        textAlign: compact ? "center" as const : "left" as const,
    };

    // subtitle（ビフォーアフター・補足情報）スタイル
    const subtitleStyle: React.CSSProperties = {
        fontFamily, fontSize: 48, fontWeight: 700,
        color: "rgba(255,255,255,0.8)", marginBottom: 2,
        lineHeight: 1.2,
    };

    const valueStyle: React.CSSProperties = {
        fontFamily, fontSize: 80, fontWeight: 900,
        color: sentimentColor,
    };

    // ====== 1. 棒グラフ ======
    if (chartData.type === "bar") {
        const maxVal = chartData.maxValue || 100;
        const barPercent = (chartData.value / maxVal) * animProgress * 100;
        const displayValue = chartData.value < 10
            ? (chartData.value * animProgress).toFixed(1)
            : Math.round(chartData.value * animProgress);

        return (
            <div style={containerStyle}>
                <div style={labelStyle}>{chartData.label}</div>
                <div style={{
                    width: "100%", height: 28,
                    backgroundColor: "rgba(255,255,255,0.15)",
                    borderRadius: 8, overflow: "hidden",
                }}>
                    <div style={{
                        width: `${barPercent}%`, height: "100%",
                        backgroundColor: sentimentColor, borderRadius: 8,
                    }} />
                </div>
                <div style={{ ...valueStyle, fontSize: 80, textAlign: "right", marginTop: 2 }}>
                    {displayValue}<span style={{ fontSize: 40, marginLeft: 4, color: "#ccc" }}>{chartData.unit}</span>
                </div>
            </div>
        );
    }

    // ====== 2. 数値カウントアップ ======
    if (chartData.type === "number") {
        const displayValue = Math.round(chartData.value * animProgress);
        const formattedValue = displayValue.toLocaleString();
        // 桁数に応じてフォントサイズを動的調整（コンテナ幅1320pxに確実に収まる範囲）
        const digitLen = formattedValue.length;
        const numFontSize = compact
            ? (digitLen <= 3 ? 130 : digitLen <= 5 ? 100 : digitLen <= 7 ? 80 : 64)
            : (digitLen <= 3 ? 280 : digitLen <= 5 ? 200 : digitLen <= 7 ? 160 : digitLen <= 9 ? 120 : 100);

        // ネガティブ値: 赤色 + バウンスアニメーション
        const isNeg = chartData.negative === true;
        const bounceScale = isNeg ? interpolate(
            elapsed % 30, [0, 8, 16, 24, 30], [1, 1.12, 0.95, 1.06, 1],
            { extrapolateRight: "clamp", extrapolateLeft: "clamp" }
        ) : 1;
        const negColor = "#FF3333";
        const numColor = isNeg ? negColor : sentimentColor;

        return (
            <div style={containerStyle}>
                <div style={labelStyle}>{chartData.label}</div>
                {chartData.subtitle && <div style={subtitleStyle}>{chartData.subtitle}</div>}
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "center", gap: compact ? 6 : 12, marginTop: compact ? 16 : "auto", flexWrap: compact ? "wrap" : "nowrap" }}>
                    <span style={{
                        ...valueStyle,
                        fontSize: numFontSize,
                        lineHeight: 1.1,
                        color: numColor,
                        transform: `scale(${bounceScale})`,
                        display: "inline-block",
                        textShadow: isNeg ? "0 0 20px rgba(255,50,50,0.6), 0 0 40px rgba(255,0,0,0.3)" : "none",
                    }}>{formattedValue}</span>
                    <span style={{ fontFamily, fontSize: Math.max(32, Math.round(numFontSize * 0.4)), fontWeight: 700, color: isNeg ? "#ff6666" : "#ccc" }}>{chartData.unit}</span>
                </div>
            </div>
        );
    }

    // ====== 3. 円グラフ（パイチャート） ======
    if (chartData.type === "pie") {
        const maxVal = chartData.maxValue || 100;
        const percentage = chartData.value / maxVal;
        const radius = 180;
        const circumference = 2 * Math.PI * radius;
        const dashOffset = circumference * (1 - percentage * animProgress);
        const displayValue = Math.round(chartData.value * animProgress);

        return (
            <div style={{ ...containerStyle, flexDirection: "row", alignItems: "center", gap: 40 }}>
                <div style={{ position: "relative", width: 440, height: 440, flexShrink: 0 }}>
                    <svg width="440" height="440" viewBox="0 0 440 440">
                        {/* 背景円 */}
                        <circle cx="220" cy="220" r={radius} fill="none"
                            stroke="rgba(255,255,255,0.15)" strokeWidth="28" />
                        {/* データ円 */}
                        <circle cx="220" cy="220" r={radius} fill="none"
                            stroke={sentimentColor} strokeWidth="30"
                            strokeDasharray={circumference}
                            strokeDashoffset={dashOffset}
                            strokeLinecap="round"
                            transform="rotate(-90 220 220)" />
                    </svg>
                </div>
                <div>
                    <div style={labelStyle}>{chartData.label}</div>
                    <div style={valueStyle}>
                        {displayValue}{chartData.unit}
                    </div>
                </div>
            </div>
        );
    }

    // ====== 4. ドーナツチャート ======
    if (chartData.type === "donut") {
        const maxVal = chartData.maxValue || 100;
        const percentage = chartData.value / maxVal;
        const radius = 190;
        const circumference = 2 * Math.PI * radius;
        const dashOffset = circumference * (1 - percentage * animProgress);
        const displayValue = Math.round(chartData.value * animProgress);

        return (
            <div style={{ ...containerStyle, flexDirection: "row", alignItems: "center", gap: 40 }}>
                <div style={{ position: "relative", width: 440, height: 440, flexShrink: 0 }}>
                    <svg width="440" height="440" viewBox="0 0 440 440">
                        <circle cx="220" cy="220" r={radius} fill="none"
                            stroke="rgba(255,255,255,0.15)" strokeWidth="22" />
                        <circle cx="220" cy="220" r={radius} fill="none"
                            stroke={sentimentColor} strokeWidth="22"
                            strokeDasharray={circumference}
                            strokeDashoffset={dashOffset}
                            strokeLinecap="round"
                            transform="rotate(-90 220 220)" />
                    </svg>
                    {/* 中央の数値 */}
                    <div style={{
                        position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
                        display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                        <span style={{
                            fontFamily, fontSize: 120, fontWeight: 900, color: "#fff",
                        }}>
                            {displayValue}<span style={{ fontSize: 64 }}>{chartData.unit}</span>
                        </span>
                    </div>
                </div>
                <div>
                    <div style={labelStyle}>{chartData.label}</div>
                </div>
            </div>
        );
    }

    // ====== 5. 横型比較バー（アンケート形式） ======
    if (chartData.type === "compare") {
        const total = chartData.value + (chartData.compareValue || 0);
        const leftPercent = (chartData.value / total) * animProgress * 100;
        const rightPercent = ((chartData.compareValue || 0) / total) * animProgress * 100;
        const leftDisplay = Math.round((chartData.value / total) * 100 * animProgress);
        const rightDisplay = Math.round(((chartData.compareValue || 0) / total) * 100 * animProgress);

        return (
            <div style={containerStyle}>
                <div style={labelStyle}>{chartData.label}</div>
                <div style={{ display: "flex", gap: 4, width: "100%", height: 90, borderRadius: 45, overflow: "hidden" }}>
                    <div style={{
                        width: `${leftPercent}%`, height: "100%",
                        backgroundColor: sentimentColor, borderRadius: "18px 0 0 18px",
                        display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                        {leftPercent > 15 && (
                            <span style={{ fontFamily, fontSize: 64, fontWeight: "bold", color: "#fff" }}>
                                {leftDisplay}%
                            </span>
                        )}
                    </div>
                    <div style={{
                        width: `${rightPercent}%`, height: "100%",
                        backgroundColor: "#666", borderRadius: "0 18px 18px 0",
                        display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                        {rightPercent > 15 && (
                            <span style={{ fontFamily, fontSize: 64, fontWeight: "bold", color: "#fff" }}>
                                {rightDisplay}%
                            </span>
                        )}
                    </div>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
                    <span style={{ fontFamily, fontSize: 48, fontWeight: "bold", color: sentimentColor }}>
                        {leftDisplay}{chartData.unit}
                    </span>
                    <span style={{ fontFamily, fontSize: 48, fontWeight: "bold", color: "#999" }}>
                        {chartData.compareLabel || "その他"} {rightDisplay}{chartData.unit}
                    </span>
                </div>
            </div>
        );
    }

    // ====== 6. フリップカード ======
    if (chartData.type === "flipcard") {
        const flipProgress = interpolate(elapsed, [5, 30], [0, 180], {
            extrapolateRight: "clamp", extrapolateLeft: "clamp",
        });
        const showFront = flipProgress < 90;
        const displayValue = chartData.value < 10
            ? chartData.value.toFixed(1)
            : chartData.value.toLocaleString();

        return (
            <div style={{ ...containerStyle, perspective: 800 }}>
                <div style={labelStyle}>{chartData.label}</div>
                <div style={{
                    width: "100%", height: 180,
                    transformStyle: "preserve-3d",
                    transform: `rotateY(${flipProgress}deg)`,
                }}>
                    {showFront ? (
                        <div style={{
                            width: "100%", height: "100%",
                            backgroundColor: "rgba(255,255,255,0.1)",
                            borderRadius: 10, display: "flex",
                            alignItems: "center", justifyContent: "center",
                            backfaceVisibility: "hidden",
                        }}>
                            <span style={{ fontFamily, fontSize: 48, color: "#aaa" }}>???</span>
                        </div>
                    ) : (
                        <div style={{
                            width: "100%", height: "100%",
                            backgroundColor: sentimentColor,
                            borderRadius: 10, display: "flex",
                            alignItems: "center", justifyContent: "center",
                            transform: "rotateY(180deg)",
                            backfaceVisibility: "hidden",
                        }}>
                            <span style={{
                                fontFamily, fontSize: 80, fontWeight: 900, color: "#fff",
                            }}>
                                {displayValue}<span style={{ fontSize: 40 }}>{chartData.unit}</span>
                            </span>
                        </div>
                    )}
                </div>
            </div>
        );
    }

    // ====== 7. ランキングリスト ======
    if (chartData.type === "ranking" && chartData.items) {
        const maxItemValue = Math.max(...chartData.items.map(i => i.value));
        return (
            <div style={containerStyle}>
                <div style={labelStyle}>{chartData.label}</div>
                {chartData.items.slice(0, 3).map((item, i) => {
                    const itemDelay = i * 15;
                    const itemProgress = interpolate(elapsed - itemDelay, [0, 20], [0, 1], {
                        extrapolateRight: "clamp", extrapolateLeft: "clamp",
                    });
                    const slideX = (1 - itemProgress) * 200;
                    const barW = (item.value / maxItemValue) * itemProgress * 100;
                    const medals = ["#FFD700", "#C0C0C0", "#CD7F32"];

                    return (
                        <div key={i} style={{
                            display: "flex", alignItems: "center", gap: 8,
                            marginBottom: 6, opacity: itemProgress,
                            transform: `translateX(${slideX}px)`,
                        }}>
                            <div style={{
                                width: 28, height: 28, borderRadius: 14,
                                backgroundColor: medals[i], display: "flex",
                                alignItems: "center", justifyContent: "center",
                                fontFamily, fontSize: 24, fontWeight: 900, color: "#000",
                                flexShrink: 0,
                            }}>
                                {i + 1}
                            </div>
                            <div style={{ flex: 1 }}>
                                <div style={{
                                    fontFamily, fontSize: 48, color: "#fff",
                                    marginBottom: 2,
                                }}>
                                    {item.label}
                                </div>
                                <div style={{
                                    height: 28, backgroundColor: "rgba(255,255,255,0.15)",
                                    borderRadius: 14, overflow: "hidden",
                                }}>
                                    <div style={{
                                        width: `${barW}%`, height: "100%",
                                        backgroundColor: sentimentColor, borderRadius: 5,
                                    }} />
                                </div>
                            </div>
                            <span style={{
                                fontFamily, fontSize: 56, fontWeight: 900, color: sentimentColor,
                                flexShrink: 0,
                            }}>
                                {Math.round(item.value * itemProgress)}{chartData.unit}
                            </span>
                        </div>
                    );
                })}
            </div>
        );
    }

    // ====== 8. アンケート／世論調査（poll） ======
    if (chartData.type === "poll" && chartData.items) {
        const totalVotes = chartData.items.reduce((acc, i) => acc + i.value, 0);
        const itemCount = Math.min(chartData.items.length, 5);
        // 項目数に応じてフォントサイズを動的縮小
        const pollLabelSize = itemCount <= 2 ? 72 : itemCount <= 3 ? 60 : itemCount <= 4 ? 50 : 42;
        const pollPctSize = itemCount <= 2 ? 80 : itemCount <= 3 ? 64 : itemCount <= 4 ? 52 : 44;
        const pollBarHeight = itemCount <= 2 ? 24 : itemCount <= 3 ? 18 : 14;
        const pollGap = itemCount <= 3 ? 4 : 2;
        return (
            <div style={containerStyle}>
                <div style={{
                    fontFamily, fontSize: labelFontSize, fontWeight: 900,
                    color: "#fff", marginBottom: 4,
                    lineHeight: 1.2, wordBreak: "keep-all", overflowWrap: "break-word",
                }}>
                    <span style={{ color: sentimentColor, marginRight: 8 }}>|</span>
                    {chartData.label}
                </div>
                <div style={{
                    fontFamily, fontSize: 28, color: "rgba(255,255,255,0.5)",
                    marginBottom: 8,
                }}>
                    {totalVotes > 0 ? `${Math.round(totalVotes)}人に聞きました` : "みんなの声"}
                </div>
                {chartData.items.slice(0, 5).map((item, i) => {
                    const itemDelay = i * 10;
                    const itemProgress = interpolate(elapsed - itemDelay, [0, 25], [0, 1], {
                        extrapolateRight: "clamp", extrapolateLeft: "clamp",
                    });
                    const pct = totalVotes > 0 ? (item.value / totalVotes) * 100 : 0;
                    const barW = (pct / 100) * itemProgress * 100;
                    const isTop = i === 0;
                    const isQuizHidden = item.label === "？？？";
                    const rankColors = [sentimentColor, "#2ECC71", "#27AE60", "#1ABC9C", "#16A085"];
                    const itemColor = rankColors[i] || "#2ECC71";

                    return (
                        <div key={i} style={{
                            marginBottom: pollGap, opacity: itemProgress,
                            transform: `translateX(${(1 - itemProgress) * 60}px)`,
                        }}>
                            <div style={{
                                display: "flex", justifyContent: "space-between",
                                alignItems: "baseline", marginBottom: 2,
                            }}>
                                <span style={{
                                    fontFamily, fontSize: isTop ? pollLabelSize * 1.2 : pollLabelSize,
                                    fontWeight: 900,
                                    color: isQuizHidden ? "#FFD700" : isTop ? "#fff" : "rgba(255,255,255,0.85)",
                                    textShadow: isQuizHidden ? "0 0 20px #FFD700, 0 0 40px #FF8C00" : "none",
                                    background: isQuizHidden ? "linear-gradient(135deg, rgba(255,215,0,0.2), rgba(255,140,0,0.15))" : "none",
                                    padding: isQuizHidden ? "4px 16px" : "0",
                                    borderRadius: isQuizHidden ? 8 : 0,
                                    border: isQuizHidden ? "2px solid rgba(255,215,0,0.5)" : "none",
                                }}>
                                    {item.label}
                                </span>
                                <span style={{
                                    fontFamily, fontSize: isTop ? pollPctSize * 1.2 : pollPctSize,
                                    fontWeight: 900,
                                    color: isQuizHidden ? "#FFD700" : isTop ? sentimentColor : "rgba(255,255,255,0.7)",
                                    textShadow: isQuizHidden ? "0 0 15px #FFD700" : "none",
                                }}>
                                    {isQuizHidden ? "??%" : `${Math.round(pct * itemProgress)}%`}
                                </span>
                            </div>
                            <div style={{
                                height: isTop ? pollBarHeight * 1.3 : pollBarHeight,
                                backgroundColor: "rgba(255,255,255,0.1)",
                                borderRadius: 6, overflow: "hidden",
                            }}>
                                <div style={{
                                    width: `${barW}%`, height: "100%",
                                    backgroundColor: isQuizHidden ? "#FFD700" : itemColor,
                                    borderRadius: 6,
                                    boxShadow: isQuizHidden ? "0 0 12px rgba(255,215,0,0.6)" : "none",
                                }} />
                            </div>
                        </div>
                    );
                })}
            </div>
        );
    }

    // フォールバック: number表示
    const displayValue = Math.round(chartData.value * animProgress);
    return (
        <div style={containerStyle}>
            <div style={labelStyle}>{chartData.label}</div>
            <div style={{ ...valueStyle, fontSize: 64, textAlign: "center" }}>
                {displayValue.toLocaleString()}<span style={{ fontSize: 32, marginLeft: 8, color: "#ccc" }}>{chartData.unit}</span>
            </div>
        </div>
    );
};
