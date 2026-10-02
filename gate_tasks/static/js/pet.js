// Desktop pet for Gate Tasks (core vendored from github.com/louzinio/desktop-pet-skill, MIT).
// Choose Clawd, Amir Latex or Earl Grey the British Shorthair from the header; the choice and the
// on/off switch are remembered per browser. Disable server-wide with GATE_TASKS_PET=0.

const toggle = document.getElementById('pet-toggle');
const skinSelect = document.getElementById('pet-skin');
const SKIN_KEYS = ['clawd', 'cat', 'bsh'];
// Perches: default widgets plus Gate Tasks' cards, column headers and panels, skipping anything
// inside the dialog while it is closed and the header controls (so it never covers them).
const EXTRA = '.task-card,.column-header,.creation-bar,.chart-box,.user-profile,.search-container';

const store = {
    get(key) { try { return localStorage.getItem(key); } catch (e) { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* private mode */ } },
};

let attachPet = null;
let defaultPerches = '';
let skin = SKIN_KEYS.includes(store.get('gateTasksPetSkin')) ? store.get('gateTasksPetSkin') : 'clawd';
skinSelect.value = skin;

async function startPet() {
    if (window.gatePet) return;
    try {
        if (!attachPet) {
            ({ attachPet, DEFAULT_PERCHES: defaultPerches } = await import('/static/pet/pet-dom.js'));
            try { await import('/static/pet/pet-bsh.js'); } catch (e) { console.warn('British Shorthair skin unavailable:', e); }
        }
        const perches = `:is(${defaultPerches},${EXTRA}):not(#expansion-modal:not(.active) *):not(.header *)`;
        window.gatePet = attachPet({ skin, perches, dark: true });
    } catch (e) {
        console.warn('Desktop pet failed to start:', e);
        window.gatePet = null;
    }
}

function stopPet() {
    try { window.gatePet?.stop(); } catch (e) { /* already gone */ }
    window.gatePet = null;
}

function sync(on) {
    toggle.classList.toggle('on', on);
    toggle.textContent = on ? '🐾 Pet: On' : '🐾 Pet: Off';
    skinSelect.disabled = !on;
    if (on) startPet(); else stopPet();
}

if (window.GATE_TASKS?.petEnabled) {
    toggle.style.display = '';
    skinSelect.style.display = '';
    let on = store.get('gateTasksPet') !== 'off';
    toggle.addEventListener('click', () => { on = !on; store.set('gateTasksPet', on ? 'on' : 'off'); sync(on); });
    skinSelect.addEventListener('change', () => {
        skin = skinSelect.value;
        store.set('gateTasksPetSkin', skin);
        window.gatePet?.setSkin(skin);
        window.gatePet?.core.cheer();
    });
    sync(on);
}
