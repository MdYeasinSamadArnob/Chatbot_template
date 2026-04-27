"use client";

import { RotateCcw, Shield } from "lucide-react";
import clsx from "clsx";
import type { ConnectionStatus } from "@/store/types";

interface Props {
  onReset: () => void;
  connectionStatus?: ConnectionStatus;
}

export function ChatHeader({ onReset, connectionStatus = "disconnected" }: Props) {
  const statusColor = {
    connected: "bg-green-400",
    reconnecting: "bg-yellow-400 animate-pulse",
    disconnected: "bg-red-400",
  }[connectionStatus];

  const statusLabel = {
    connected: "Online",
    reconnecting: "Reconnecting...",
    disconnected: "Offline",
  }[connectionStatus];

  return (
    <div className="flex items-center gap-3 px-4 h-14 bg-[#0A1628] flex-shrink-0 shadow-lg">
      {/* Bank shield icon */}
      <div className="w-8 h-8 rounded-full bg-[#1A56DB] flex items-center justify-center flex-shrink-0">
        <Shield size={16} className="text-white" />
      </div>

      {/* Title + subtitle */}
      <div className="flex-1 min-w-0">
        <p className="text-white font-semibold text-sm leading-tight truncate">
          Help &amp; Support
        </p>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className={clsx("w-1.5 h-1.5 rounded-full flex-shrink-0", statusColor)} />
          <span className="text-gray-400 text-[10px] leading-tight">{statusLabel}</span>
        </div>
      </div>

      {/* Reset conversation */}
      <button
        onClick={onReset}
        title="Reset conversation"
        className="w-9 h-9 flex items-center justify-center rounded-full text-gray-400 hover:text-white hover:bg-white/10 transition-colors active:scale-95"
      >
        <RotateCcw size={15} />
      </button>
    </div>
  );
}
