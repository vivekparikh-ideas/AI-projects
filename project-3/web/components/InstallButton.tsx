"use client";
// Offers "Install Nexus" when Chrome says the app is installable (Android/desktop), so installing is one tap.
import { useEffect, useState } from "react";

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export function InstallButton() {
  const [prompt, setPrompt] = useState<InstallPromptEvent | null>(null);
  useEffect(() => {
    const onPrompt = (e: Event) => {
      e.preventDefault(); // keep the event so our button can show the browser's install dialog
      setPrompt(e as InstallPromptEvent);
    };
    const onInstalled = () => setPrompt(null);
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);
  if (!prompt) return null;
  return (
    <button className="btn primary small" onClick={async () => { await prompt.prompt(); await prompt.userChoice; setPrompt(null); }}>
      Install Nexus
    </button>
  );
}
