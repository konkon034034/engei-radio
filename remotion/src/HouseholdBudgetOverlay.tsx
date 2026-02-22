/**
 * HouseholdBudgetOverlay.tsx
 * パターンA: ドキュメンタリー型 - 家計簿オーバーレイ（neeeenkin専用）
 *
 * 年金生活者の1ヶ月の家計を「家計簿」形式で常時表示する。
 * 収入（年金額）と支出（家賃・食費・医療費等）を見せて
 * 「自分もこうなるかも」という損得感情を刺激する。
 */
import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansJP";

const { fontFamily } = loadFont();

export interface HouseholdBudgetData {
    personLabel: string;       // 例: "73歳女性・一人暮らし"
    income: number;            // 年金月額（円）
    expenses: { label: string; amount: number }[]; // 支出内訳
}

export const HouseholdBudgetOverlay: React.FC<{
    data: HouseholdBudgetData;
    startFrame: number;
    channelColor: string;
}> = ({ data, startFrame, channelColor }) => {
    const frame = useCurrentFrame();
    const elapsed = frame - startFrame;

    // フェードイン
    const opacity = interpolate(elapsed, [0, 20], [0, 1], {
        extrapolateRight: "clamp", extrapolateLeft: "clamp",
    });

    if (opacity <= 0) return null;

    const totalExpenses = data.expenses.reduce((sum, e) => sum + e.amount, 0);
    const remaining = data.income - totalExpenses;
    const isDeficit = remaining < 0;

    // 各項目の遅延アニメーション
    const itemAnim = (index: number) => {
        const delay = 10 + index * 8;
        return interpolate(elapsed - delay, [0, 15], [0, 1], {
            extrapolateRight: "clamp", extrapolateLeft: "clamp",
        });
    };

    return (
        <div style={{
            position: "absolute",
            top: 10,
            left: 810,
            width: 820,
            height: 640,
            backgroundColor: "rgba(0, 0, 0, 0.88)",
            borderRadius: 16,
            padding: "24px 28px",
            opacity,
            zIndex: 30,
            borderLeft: `6px solid ${channelColor}`,
            boxSizing: "border-box",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
        }}>
            {/* ヘッダー: 人物ラベル */}
            <div style={{
                fontFamily, fontSize: 36, fontWeight: 900,
                color: "#FFD700", marginBottom: 8,
                borderBottom: "3px solid rgba(255,255,255,0.25)",
                paddingBottom: 10,
            }}>
                {data.personLabel}の家計簿
            </div>

            {/* 収入 */}
            <div style={{
                display: "flex", justifyContent: "space-between",
                fontFamily, fontSize: 38, fontWeight: 700,
                color: "#4CAF50", marginBottom: 8,
            }}>
                <span>年金収入</span>
                <span>{data.income.toLocaleString()}円</span>
            </div>

            {/* 支出明細 */}
            <div style={{
                borderTop: "2px solid rgba(255,255,255,0.15)",
                paddingTop: 8, flex: 1,
                display: "flex", flexDirection: "column",
                justifyContent: "space-evenly",
            }}>
                {data.expenses.map((exp, i) => {
                    const progress = itemAnim(i);
                    return (
                        <div key={i} style={{
                            display: "flex", justifyContent: "space-between",
                            fontFamily, fontSize: 32, fontWeight: 600,
                            color: "rgba(255,255,255,0.9)",
                            opacity: progress,
                            transform: `translateX(${(1 - progress) * 30}px)`,
                        }}>
                            <span>{exp.label}</span>
                            <span>-{exp.amount.toLocaleString()}円</span>
                        </div>
                    );
                })}
            </div>

            {/* 残金 */}
            <div style={{
                borderTop: "3px solid rgba(255,255,255,0.3)",
                marginTop: 6, paddingTop: 10,
                display: "flex", justifyContent: "space-between",
                fontFamily, fontSize: 44, fontWeight: 900,
                color: isDeficit ? "#FF3333" : "#FFD700",
            }}>
                <span>残り</span>
                <span>{remaining.toLocaleString()}円</span>
            </div>

            {/* 残金バー */}
            <div style={{
                height: 12, backgroundColor: "rgba(255,255,255,0.15)",
                borderRadius: 6, marginTop: 8, overflow: "hidden",
            }}>
                <div style={{
                    height: "100%",
                    width: `${Math.max(0, Math.min(100, (remaining / data.income) * 100))}%`,
                    backgroundColor: isDeficit ? "#FF3333" : "#4CAF50",
                    borderRadius: 6,
                    transition: "width 0.3s",
                }} />
            </div>
        </div>
    );
};
