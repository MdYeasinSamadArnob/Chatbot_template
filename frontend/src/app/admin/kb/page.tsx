"use client";

import { useEffect } from "react";

const EDITOR_APP_URL = process.env.NEXT_PUBLIC_EDITOR_APP_URL || "http://localhost:3002";

export default function AdminKBPage() {
  useEffect(() => {
    window.location.replace(EDITOR_APP_URL);
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-6">
      <div className="w-full max-w-xl rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-gray-400">
          Knowledge Base
        </p>
        <h1 className="mt-3 text-2xl font-semibold text-gray-900">
          KB editing moved to the dedicated editor app.
        </h1>
        <p className="mt-3 text-sm leading-6 text-gray-600">
          Redirecting now. All document creation and editing should be done in the standalone
          editor so the workflow lives in one place.
        </p>
        <div className="mt-6 flex items-center gap-3">
          <a
            href={EDITOR_APP_URL}
            className="inline-flex items-center rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800"
          >
            Open KB Editor
          </a>
          <a
            href="/"
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Back to chat
          </a>
        </div>
      </div>
    </div>
  );
}
