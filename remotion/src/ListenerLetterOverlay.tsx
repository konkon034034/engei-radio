/**
 * ListenerLetterOverlay.tsx
 * パターンC: お便りラジオ型 - リスナーの手紙（seiji-channel専用）
 * 
 * 「視聴者のお便り」形式で悩みを画面に表示。
 * カツミとヒロシがその内容について対談する形式。
 * 「わかるわ...」という共感を刺激する。
 */
import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansJP";

const { fontFamily } = loadFont();

export interface ListenerLetterData {
    senderLabel: string;  // 例: "68歳・主婦・東京都"
    letterText: string;   // お便り本文
}

export const ListenerLetterOverlay: React.FC<{
    data: ListenerLetterData;
    startFrame: number;
    channelColor: string;
}> = ({ data, startFrame, channelColor }) => {
    const frame = useCurrentFrame();
    const elapsed = frame - startFrame;

    // フェードイン
    const opacity = interpolate(elapsed, [0, 25], [0, 1], {
        extrapolateRight: "clamp", extrapolateLeft: "clamp",
    });

    if (opacity <= 0) return null;

    // 手紙本文の文字を1文字ずつ表示（タイプライター演出）
    const visibleChars = Math.min(
        data.letterText.length,
        Math.floor(interpolate(elapsed, [20, 20 + data.letterText.length * 2], [0, data.letterText.length], {
            extrapolateRight: "clamp", extrapolateLeft: "clamp",
        }))
    );

    return (
        <div style={{
            position: "absolute",
            top: 10,
            right: 310,
            width: 520,
            backgroundColor: "rgba(0, 0, 0, 0.88)",
            borderRadius: 12,
            padding: "16px 20px",
            opacity,
            zIndex: 45,
            borderLeft: `5px solid ${channelColor}`,
            boxSizing: "border-box",
        }}>
            {/* ヘッダー: お便りマーク */}
            <div style={{
                fontFamily, fontSize: 26, fontWeight: 900,
                color: "#FFD700", marginBottom: 8,
                borderBottom: "2px solid rgba(255,255,255,0.2)",
                paddingBottom: 6,
                textAlign: "center",
            }}>
                今日のお便り
            </div>

            {/* 差出人 */}
            <div style={{
                fontFamily, fontSize: 20, fontWeight: 500,
                color: "rgba(255,255,255,0.6)", marginBottom: 10,
                textAlign: "right",
            }}>
                {data.senderLabel} さんより
            </div>

            {/* 手紙本文 */}
            <div style={{
                fontFamily, fontSize: 22, fontWeight: 500,
                color: "#ffffff",
                lineHeight: 1.6,
                padding: "10px 8px",
                backgroundColor: "rgba(255,255,255,0.06)",
                borderRadius: 8,
                border: "1px solid rgba(255,255,255,0.1)",
                minHeight: 120,
                maxHeight: 350,
                overflow: "hidden",
            }}>
                <span style={{ color: "rgba(255,215,0,0.7)", fontSize: 28 }}>「</span>
                {data.letterText.slice(0, visibleChars)}
                {visibleChars < data.letterText.length && (
                    <span style={{
                        opacity: Math.sin(frame * 0.3) > 0 ? 1 : 0,
                        color: "#FFD700",
                    }}>|</span>
                )}
                {visibleChars >= data.letterText.length && (
                    <span style={{ color: "rgba(255,215,0,0.7)", fontSize: 28 }}>」</span>
                )}
            </div>
        </div>
    );
};
