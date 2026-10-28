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
    });
})();
