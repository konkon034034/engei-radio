/**
 * ChecklistOverlay.tsx
 * パターンB: チェックリスト型 - もらえるお金チェック（kyufukin-channel専用）
 * 
 * 給付金・制度を「チェックリスト」形式で表示。
 * 台本の進行に合わせて項目が1つずつチェックされていく。
 * 「もらい忘れてない？」という損失回避を刺激する。
 */
import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansJP";

const { fontFamily } = loadFont();

export interface ChecklistItem {
    label: string;           // 制度名
    amount: string;          // 金額（例: "月5,310円"）
    checkedAtFrame: number;  // チェックがつくフレーム
}

export interface ChecklistData {
    title: string;           // 例: "もらえるお金チェックリスト"
    items: ChecklistItem[];
}

export const ChecklistOverlay: React.FC<{
    data: ChecklistData;
    channelColor: string;
}> = ({ data, channelColor }) => {
    const frame = useCurrentFrame();

    // フェードイン
    const opacity = interpolate(frame, [0, 20], [0, 1], {
        extrapolateRight: "clamp", extrapolateLeft: "clamp",
    });

    if (opacity <= 0) return null;

    return (
        <div style={{
            position: "absolute",
            top: 10,
            right: 310,
            width: 520,
            backgroundColor: "rgba(0, 0, 0, 0.88)",
            borderRadius: 12,
            padding: "14px 18px",
            opacity,
            zIndex: 45,
            borderLeft: `5px solid ${channelColor}`,
            boxSizing: "border-box",
        }}>
            {/* ヘッダー */}
            <div style={{
                fontFamily, fontSize: 28, fontWeight: 900,
                color: "#FFD700", marginBottom: 10,
                textAlign: "center",
                borderBottom: "2px solid rgba(255,255,255,0.2)",
                paddingBottom: 8,
            }}>
                {data.title}
            </div>

            {/* チェックリスト */}
            {data.items.map((item, i) => {
                const isChecked = frame >= item.checkedAtFrame;
                const checkAnim = interpolate(
                    frame - item.checkedAtFrame, [0, 10], [0, 1],
                    { extrapolateRight: "clamp", extrapolateLeft: "clamp" }
                );
                const itemOpacity = interpolate(
                    frame, [i * 8, i * 8 + 15], [0, 1],
                    { extrapolateRight: "clamp", extrapolateLeft: "clamp" }
                );

                return (
                    <div key={i} style={{
                        display: "flex", alignItems: "center", gap: 10,
                        marginBottom: 8, opacity: itemOpacity,
                        transform: `translateX(${(1 - itemOpacity) * 20}px)`,
                    }}>
                        {/* チェックボックス */}
                        <div style={{
                            width: 32, height: 32, borderRadius: 6,
                            border: `3px solid ${isChecked ? "#4CAF50" : "rgba(255,255,255,0.4)"}`,
                            backgroundColor: isChecked ? "rgba(76,175,80,0.3)" : "transparent",
                            display: "flex", alignItems: "center", justifyContent: "center",
                            flexShrink: 0,
                        }}>
                            {isChecked && (
                                <span style={{
                                    fontFamily, fontSize: 22, fontWeight: 900,
                                    color: "#4CAF50",
                                    opacity: checkAnim,
                                    transform: `scale(${0.5 + checkAnim * 0.5})`,
                                }}>
                                    OK
                                </span>
                            )}
                        </div>

                        {/* ラベルと金額 */}
                        <div style={{ flex: 1 }}>
                            <div style={{
                                fontFamily, fontSize: 24, fontWeight: 700,
                                color: isChecked ? "#4CAF50" : "#ffffff",
                                textDecoration: isChecked ? "none" : "none",
                            }}>
                                {item.label}
                            </div>
                            <div style={{
                                fontFamily, fontSize: 20, fontWeight: 500,
                                color: isChecked ? "rgba(76,175,80,0.8)" : "rgba(255,255,255,0.6)",
                            }}>
                                {item.amount}
                            </div>
                        </div>

                        {/* 金額ハイライト */}
                        {isChecked && (
                            <div style={{
                                fontFamily, fontSize: 22, fontWeight: 900,
                                color: "#FFD700",
                                opacity: checkAnim,
                            }}>
                                GET!
                            </div>
                        )}
                    </div>
                );
            })}

            {/* 合計 */}
            {(() => {
                const checkedItems = data.items.filter(item => frame >= item.checkedAtFrame);
                if (checkedItems.length === 0) return null;
                return (
                    <div style={{
                        borderTop: "2px solid rgba(255,255,255,0.3)",
                        marginTop: 6, paddingTop: 6,
                        fontFamily, fontSize: 22, fontWeight: 700,
                        color: "#FFD700", textAlign: "center",
                    }}>
                        {checkedItems.length}/{data.items.length} 件確認済み
                    </div>
                );
            })()}
        </div>
    );
};
