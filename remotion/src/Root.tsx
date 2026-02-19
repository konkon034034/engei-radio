import React from "react";
import { Composition, getInputProps } from "remotion";
import { KamishibaiVideo } from "./KamishibaiVideo";

const inputProps = getInputProps();

export const RemotionRoot: React.FC = () => {
    return (
        <>
            <Composition
                id="KamishibaiVideo"
                component={KamishibaiVideo}
                durationInFrames={inputProps.kamishibaiDuration || 4320}
                fps={24}
                width={1920}
                height={1080}
                defaultProps={{
                    slides: inputProps.kamishibaiSlides || [],
                    bgmPath: inputProps.kamishibaiBgm || "hikaeshitsu_bgm.mp3",
                    bgmVolume: 0.15,
                    channelName: inputProps.channelName || "",
                    channelColor: inputProps.channelColor || "#8B4513",
                    durationInFrames: inputProps.kamishibaiDuration || 4320,
                }}
            />
        </>
    );
};
