"use client";

import type { UserTextMessage as UserTextMessageType } from "@/store/types";

interface Props {
  message: UserTextMessageType;
}

export function UserMessage({ message }: Props) {
  return (
    <div className="flex justify-end px-4 py-1.5">
      <div className="max-w-[86%] md:max-w-[64%] xl:max-w-[560px] bg-[#1A56DB] text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed shadow-sm">
        {message.text}
      </div>
    </div>
  );
}

