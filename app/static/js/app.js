// Gemeinsames JavaScript für alle Seiten. Wird vor Alpine.js geladen.

(function () {
    const media = window.matchMedia('(prefers-color-scheme: dark)');

    function storedTheme() {
        try {
            return localStorage.getItem('theme') || 'auto';
        } catch (e) {
            return 'auto';
        }
    }

    function applyTheme(choice) {
        const dark = choice === 'dark' || (choice !== 'light' && media.matches);
        document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    }

    // System-Farbschema folgen, solange "Auto" gewählt ist
    media.addEventListener('change', () => {
        if (storedTheme() === 'auto') applyTheme('auto');
    });

    document.addEventListener('alpine:init', () => {
        // Farbschema-Umschalter: Hell / Dunkel / Auto
        Alpine.data('themeSwitcher', () => ({
            open: false,
            choice: storedTheme(),
            set(choice) {
                this.open = false;
                this.choice = choice;
                try {
                    localStorage.setItem('theme', choice);
                } catch (e) {}
                applyTheme(choice);
            },
        }));

        // Push-Benachrichtigungen für dieses Gerät ein-/ausschalten (Profilseite)
        Alpine.data('pushToggle', (cfg) => ({
            // unsupported | ios-install | denied | off | on
            state: 'off',
            busy: false,
            message: '',
            async init() {
                const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
                const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
                if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
                    // iOS kennt Web Push nur in der installierten App (Home-Bildschirm)
                    this.state = ios && !standalone ? 'ios-install' : 'unsupported';
                    return;
                }
                if (Notification.permission === 'denied') {
                    this.state = 'denied';
                    return;
                }
                const reg = await navigator.serviceWorker.ready;
                this.state = (await reg.pushManager.getSubscription()) ? 'on' : 'off';
            },
            async post(url, body) {
                const res = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cfg.csrf },
                    body: JSON.stringify(body || {}),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.error || 'Serverfehler');
                return data;
            },
            async enable() {
                this.busy = true;
                this.message = '';
                try {
                    if (await Notification.requestPermission() !== 'granted') {
                        this.state = Notification.permission === 'denied' ? 'denied' : 'off';
                        return;
                    }
                    const reg = await navigator.serviceWorker.ready;
                    const sub = await reg.pushManager.subscribe({
                        userVisibleOnly: true,
                        applicationServerKey: urlBase64ToUint8Array(cfg.publicKey),
                    });
                    await this.post(cfg.subscribeUrl, sub.toJSON());
                    this.state = 'on';
                } catch (e) {
                    this.message = 'Aktivieren fehlgeschlagen: ' + e.message;
                } finally {
                    this.busy = false;
                }
            },
            async disable() {
                this.busy = true;
                this.message = '';
                try {
                    const reg = await navigator.serviceWorker.ready;
                    const sub = await reg.pushManager.getSubscription();
                    if (sub) {
                        await this.post(cfg.unsubscribeUrl, { endpoint: sub.endpoint });
                        await sub.unsubscribe();
                    }
                    this.state = 'off';
                } catch (e) {
                    this.message = 'Deaktivieren fehlgeschlagen: ' + e.message;
                } finally {
                    this.busy = false;
                }
            },
            async test() {
                this.busy = true;
                this.message = '';
                try {
                    await this.post(cfg.testUrl);
                    this.message = 'Test-Benachrichtigung gesendet.';
                } catch (e) {
                    this.message = e.message;
                } finally {
                    this.busy = false;
                }
            },
        }));
    });

    function urlBase64ToUint8Array(base64) {
        const padded = (base64 + '='.repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
        return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
    }
})();
