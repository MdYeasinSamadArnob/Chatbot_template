"use client";

import { User } from "lucide-react";
import type { UserTextMessage as UserTextMessageType } from "@/store/types";

function formatTime(ts: number) {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

interface Props {
  message: UserTextMessageType;
}

export function UserMessage({ message }: Props) {
  return (
    <div className="flex justify-end items-end gap-2 px-4 py-1.5">
      <div className="flex flex-col items-end gap-1">
        <div className="max-w-[86%] md:max-w-[64%] xl:max-w-[560px] bg-[#1A56DB] text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed shadow-sm">
          {message.text}
        </div>
        <span className="text-[11px] text-gray-400 pr-0.5">
          {formatTime(message.timestamp)}
        </span>
      </div>
      {/* User avatar */}
      <div className="w-8 h-8 rounded-full bg-[#1A56DB] flex items-center justify-center flex-shrink-0 mb-5 shadow-sm">
        <User size={14} className="text-white" />
      </div>
    </div>
  );
}

