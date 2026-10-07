# BLHA server emoji

94 original 8-bit emoji for the server: 44 static and 50 animated. With the 6 soundboard emoji in
`brand/sounds/emoji/`, that fills the 50 static and 50 animated slots an unboosted server has.

Every emoji is a different idea. No static emoji repeats another, no animated emoji is a static one that
just moves, and none repeats a soundboard emoji.

- `static/` — 44 PNG files, 128 × 128
- `animated/` — 50 GIF files, 128 × 128, looping, each under 256 KB
- `static_a_sheet.png`, `static_b_sheet.png`, `anim_a_sheet.png`, `anim_b_sheet.png` — contact sheets
  (each GIF is shown frame by frame)
- `pix.py` plus `static_a.py`, `static_b.py`, `anim_a.py`, `anim_b.py` — the scripts that draw them.
  `python3 static_a.py` (and so on) rewrites that group's files and its sheet. Pillow only.

Style: 32 × 32 pixel art enlarged 4×, hard pixels, brand palette, a black keyline on every subject so it
reads on Discord's dark and light themes. Our players wear gold, opponents blue. No real logos or people.

## Uploading

Open **Server Settings → Emoji** and drag the files from a folder onto that page. Discord uploads them all
at once and names each emoji after its file, so nothing needs typing. Drag the 44 static files first, then the
50 animated ones; the page counts the two kinds separately (50 slots each). If Discord stops partway
through a batch, wait a minute and drag in the ones that are missing.

Members use them as `:blha_goal:` and so on, or from the server's tab in the emoji picker. Discord lets
everyone see animated emoji, but only members with Nitro can send them.

## Static (44)

| Name | Shows |
|---|---|
| blha_b | The BLHA "B" |
| blha_puck | A puck with the B on it |
| blha_stick | A stick |
| blha_mask | A goalie mask |
| blha_skate | A skate |
| blha_helmet | A gold helmet with a visor |
| blha_jersey | The gold BLHA jersey |
| blha_rink | The rink from above |
| blha_cup | The championship trophy |
| blha_banner | A championship banner |
| blha_beer | A mug of beer |
| blha_whistle | The referee's whistle |
| blha_sinbin | The penalty box with a 2-minute sign |
| blha_tape | A roll of stick tape |
| blha_bottle | A water bottle |
| blha_mitt | A player's glove |
| blha_trapper | A goalie's catching glove |
| blha_faceoff | A faceoff dot |
| blha_ice | An ice cube (ice cold) |
| blha_salty | A salt shaker |
| blha_crown | A crown |
| blha_trash | A trash can (trash talk) |
| blha_faab | A money bag with a $ (FAAB) |
| blha_contract | A signed contract with a wax seal |
| blha_pick | A "1ST" draft-pick ticket |
| blha_scout | A magnifying glass over a prospect star |
| blha_lineup | A coach's clipboard with a play drawn on it |
| blha_medal | A gold medal |
| blha_spoon | The Wooden Spoon |
| blha_pot | The Dynasty Pot: a cauldron of gold coins |
| blha_octopus | An octopus (the playoff tradition) |
| blha_tooth | A big grin with a missing front tooth |
| blha_injury | A first-aid kit |
| blha_mullet | Hockey flow, in profile |
| blha_beard | A playoff beard |
| blha_w | A big W |
| blha_l | A big L |
| blha_gg | GG |
| blha_pylon | A traffic cone (a pylon) |
| blha_sieve | A colander with pucks falling through (a leaky goalie) |
| blha_chirp | A bird mid-chirp |
| blha_apple | An apple (an assist) |
| blha_sauce | Hot sauce (a saucer pass) |
| blha_lock | A padlock (lock it in) |

## Animated (50)

| Name | What happens |
|---|---|
| blha_zamboni | The resurfacer drives across and leaves fresh ice behind |
| blha_goal | The puck flies in and the net bulges |
| blha_snipe | A target locks onto the corner and the puck hits it |
| blha_bardown | The puck rings off the crossbar and drops in |
| blha_topshelf | The puck arcs onto the top shelf beside the cookie jar, which rocks |
| blha_fivehole | The pads open, the puck slides through, the pads close too late |
| blha_dangle | The stick handles the puck side to side |
| blha_slapshot | Wind-up, slap, the puck rockets away |
| blha_snapped | A shot, and the stick snaps in two |
| blha_tilly | Two gloves drop, then the fists come up |
| blha_hattrick | Three hats rain down and pile up |
| blha_cheers | Two pints swing in and clink, foam splashes |
| blha_hockeystop | A skate digs in sideways and throws snow |
| blha_padsave | The goalie kicks out a pad and the puck deflects away |
| blha_confetti | A popper fires a burst of confetti |
| blha_jackpot | Slot reels spin and land on BBB, coins pour out |
| blha_breaking | A TV with a scrolling BREAKING ticker |
| blha_penalty | The referee raises an arm, then points to the box |
| blha_hourglass | Sand drains, then the glass flips |
| blha_fire | A flame flickers |
| blha_powerplay | A battery charges bar by bar, then a lightning bolt crackles |
| blha_laugh | Laughing so hard the tears fly |
| blha_cry | Crying a river |
| blha_mindblown | The top of the head blows off |
| blha_sweat | A nervous grin, sweat dripping |
| blha_sideeye | The eyes slide over and narrow |
| blha_facepalm | A hand slaps over the face, then slides off |
| blha_clap | Hands clap |
| blha_hello | A hand waves |
| blha_fistpump | A fist pumps, YES! |
| blha_kneeslide | The goal celebration: a knee slide with spray |
| blha_glassbang | Fists bang on the glass |
| blha_boardcheck | A gold player checks a blue player into the boards |
| blha_rat | A rat scurries across the ice |
| blha_dice | Two dice are thrown, tumble and land |
| blha_lottery | Balls tumble in the draft-lottery drum and one pops out |
| blha_popcorn | Popcorn keeps popping |
| blha_dumpsterfire | A dumpster burns |
| blha_typing | The typing dots |
| blha_rocket | A rocket lifts off on a column of smoke |
| blha_stonks | A green line climbs the chart |
| blha_tank | A red line crashes down the chart |
| blha_spotlight | A spotlight swings onto a star |
| blha_fireworks | A shell rises and bursts |
| blha_micdrop | The mic drops and bounces |
| blha_whiteflag | A white flag waves (I surrender) |
| blha_vote | A ballot drops into the box |
| blha_ghosted | A ghost fades away and comes back |
| blha_skull | A skull laughs, eyes glowing |
| blha_lfg | L, F, G stamp down one by one |
