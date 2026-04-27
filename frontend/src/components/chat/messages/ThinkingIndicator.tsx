"use client";

import { Shield } from "lucide-react";

export function ThinkingIndicator() {
  return (
    <div className="flex items-start gap-2.5 px-4 py-1.5">
      <div className="w-8 h-8 rounded-full bg-[#1A56DB] flex items-center justify-center flex-shrink-0 mt-0.5 shadow-sm">
        <Shield size={14} className="text-white" />
      </div>

      <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-sm px-4 py-3.5 shadow-sm">
        <div className="flex items-center gap-1.5">
          <span className="thinking-dot w-2 h-2 rounded-full bg-[#1A56DB] inline-block opacity-40" />
          <span className="thinking-dot w-2 h-2 rounded-full bg-[#1A56DB] inline-block opacity-40" />
          <span className="thinking-dot w-2 h-2 rounded-full bg-[#1A56DB] inline-block opacity-40" />
        </div>
      </div>
    </div>
  );
}

