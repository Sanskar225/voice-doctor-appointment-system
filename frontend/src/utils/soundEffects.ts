/**
 * Web Audio API synthesized telephone feedback tones:
 * - Soft dual-tone ringback while connecting
 * - Crisp connect chime when the Pipecat pipeline links
 * - Short descending hang-up tone when ending a call
 */

class CallSoundEngine {
  private ctx: AudioContext | null = null;
  private ringInterval: number | null = null;

  private ensureContext(): AudioContext {
    if (!this.ctx || this.ctx.state === 'closed') {
      this.ctx = new AudioContext();
    }
    if (this.ctx.state === 'suspended') {
      void this.ctx.resume();
    }
    return this.ctx;
  }

  private playRingPulse(): void {
    try {
      const ctx = this.ensureContext();
      const now = ctx.currentTime;
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.045, now + 0.04);
      gain.gain.setValueAtTime(0.045, now + 0.82);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.9);
      gain.connect(ctx.destination);

      const osc1 = ctx.createOscillator();
      const osc2 = ctx.createOscillator();
      osc1.type = 'sine';
      osc2.type = 'sine';
      osc1.frequency.setValueAtTime(440, now);
      osc2.frequency.setValueAtTime(480, now);

      osc1.connect(gain);
      osc2.connect(gain);

      osc1.start(now);
      osc2.start(now);
      osc1.stop(now + 0.92);
      osc2.stop(now + 0.92);
    } catch {
      // Ignore autoplay restrictions
    }
  }

  startRing(): void {
    this.stopRing();
    this.playRingPulse();
    this.ringInterval = window.setInterval(() => {
      this.playRingPulse();
    }, 2200);
  }

  stopRing(): void {
    if (this.ringInterval !== null) {
      window.clearInterval(this.ringInterval);
      this.ringInterval = null;
    }
  }

  playConnected(): void {
    this.stopRing();
    try {
      const ctx = this.ensureContext();
      const now = ctx.currentTime;
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.06, now + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.24);
      gain.connect(ctx.destination);

      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(587.33, now);
      osc.frequency.setValueAtTime(880, now + 0.09);
      osc.connect(gain);
      osc.start(now);
      osc.stop(now + 0.25);
    } catch {
      // Ignore audio errors
    }
  }

  playEnded(): void {
    this.stopRing();
    try {
      const ctx = this.ensureContext();
      const now = ctx.currentTime;
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.055, now + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.28);
      gain.connect(ctx.destination);

      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(480, now);
      osc.frequency.setValueAtTime(340, now + 0.12);
      osc.connect(gain);
      osc.start(now);
      osc.stop(now + 0.3);
    } catch {
      // Ignore audio errors
    }
  }
}

export const callSounds = new CallSoundEngine();
