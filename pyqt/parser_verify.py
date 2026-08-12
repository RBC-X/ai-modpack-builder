import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.repair import missing_dep_ids, version_conflicts, fatal_startup_detected

# 1. normal Forge warnings must NOT produce missing deps or fatal
warn_text = (
    "[main/WARN]: Error loading class: io/github/strikerrocker/vt/enchantments/SiphonEnchantment (java.lang.ClassNotFoundException: io.github.strikerrocker.vt.enchantments.SiphonEnchantment)\n"
    "[main/WARN]: Error loading class: net/minecraft/client/renderer/ItemRenderer (java.lang.ClassNotFoundException: net.minecraft.client.renderer.ItemRenderer)\n"
    "[main/WARN]: Error loading class: sereneseasons/season/SeasonHooks (java.lang.ClassNotFoundException: sereneseasons.season.SeasonHooks)\n"
    "[main/INFO]: Sound engine started\n"
    "[main/INFO]: Reloading ResourceManager"
)
print("1. warnings-only -> missing:", missing_dep_ids(warn_text),
      "| fatal:", fatal_startup_detected(warn_text.splitlines()))

# 2. real missing-deps screen still parses
screen = (
    "[main/ERROR]: Missing or unsupported mandatory dependencies:\n"
    "\tMod ID: 'irons_lib', Requested by: 'irons_spellbooks', Expected range: '[1.20.1-2,1.20.1-3)', Actual version: '[MISSING]'\n"
    "\tMod ID: 'curios', Requested by: 'irons_spellbooks', Expected range: '[5.14.1+1.20.1,)', Actual version: '5.6.1+1.20.1'\n"
    "\tMod ID: 'mna', Requested by: 'dmnr', Expected range: '[3.1.11,)', Actual version: '[MISSING]'"
)
print("2. missing screen -> missing:", missing_dep_ids(screen),
      "| conflicts:", [c['id'] for c in version_conflicts(screen)],
      "| fatal:", fatal_startup_detected(screen.splitlines()))

# 3. real mixin NPE crash
npe = (
    'java.lang.NullPointerException: Cannot invoke "org.spongepowered.asm.mixin.transformer.ClassInfo.getName()" because "targetClass" is null\n'
    "\tat org.spongepowered.asm.mixin.transformer.ClassInfo.getName(ClassInfo.java:123)\n"
    "\tat com.example.somemod.mixin.SomeMixin.apply(SomeMixin.java:45)\n"
    'Exception in thread "main"'
)
print("3. NPE crash -> missing:", missing_dep_ids(npe),
      "| fatal:", fatal_startup_detected(npe.splitlines()))
