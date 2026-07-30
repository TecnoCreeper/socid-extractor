# -*- coding: utf-8 -*-
"""
Regression and unit-style checks for Maigret / LLM improvement log items.

Each test documents *what* is verified (see docstrings on test functions and assertion comments).
"""
import json

from socid_extractor.main import extract
from socid_extractor.postprocessor import Gravatar, StripInvalidGravatarUrls
from socid_extractor.schemes import schemes
from socid_extractor.utils import (
    imgur_profile_avatar_url, is_bare_gravatar_root_url, is_valid_gravatar_email_hash,
    safe_deep_get, extract_next_data, next_data_page_props,
)


def test_tiktok_hydration_script_extracts_user_and_stats():
    """
    Verifies the **TikTok** scheme matches `__UNIVERSAL_DATA_FOR_REHYDRATION__` JSON (current web),
    merges `user` + `stats`, and maps ids, nickname, bio, avatar, secUid, and counters.

    **Check:** `tiktok_id`, `tiktok_username`, `fullname`, `bio`, `sec_uid`, `follower_count`,
    `following_count`, `heart_count`, `video_count`, `digg_count`, and `image` are present and
    match the embedded fixture values (legacy `SIGI_STATE` pages remain covered by a separate scheme).
    """
    user_blob = {
        'id': '9001',
        'uniqueId': 'fixtureuser',
        'nickname': 'Fixture Nick',
        'signature': 'Bio line',
        'avatarMedium': 'https://example.cdn/avatar.jpg',
        'verified': False,
        'secret': False,
        'secUid': 'MS4wLjABAAAAfixture',
    }
    stats_blob = {
        'followerCount': 10,
        'followingCount': 20,
        'heartCount': 30,
        'videoCount': 40,
        'diggCount': 50,
    }
    payload = {
        '__DEFAULT_SCOPE__': {
            'webapp.user-detail': {
                'userInfo': {
                    'user': user_blob,
                    'stats': stats_blob,
                }
            }
        }
    }
    html = (
        '<!DOCTYPE html><html><head></head><body>'
        '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
        + json.dumps(payload)
        + '</script></body></html>'
    )
    info = extract(html)
    assert info.get('tiktok_id') == '9001'
    assert info.get('tiktok_username') == 'fixtureuser'
    assert info.get('fullname') == 'Fixture Nick'
    assert info.get('bio') == 'Bio line'
    assert info.get('sec_uid') == 'MS4wLjABAAAAfixture'
    assert info.get('follower_count') == '10'
    assert info.get('following_count') == '20'
    assert info.get('heart_count') == '30'
    assert info.get('video_count') == '40'
    assert info.get('digg_count') == '50'
    assert info.get('image') == 'https://example.cdn/avatar.jpg'


def test_picsart_api_json_maps_profile_fields():
    """
    Verifies **Picsart API** scheme on a full JSON body: success payloads expose `picsart_id`,
    username, display name, photo URL, and counters.

    **Check:** `flags` match real `api.picsart.com/users/show/{user}.json` responses; numeric id is
    stringified like other fields.
    """
    body = {
        'status': 'success',  # not used as a flag; matching uses remix_score + dashboard_visibility
        'id': 184924161000102,
        'name': 'Adam',
        'username': 'adam',
        'photo': 'https://example.com/p.jpg',
        'status_message': '',
        'followers_count': 3,
        'following_count': 5,
        'likes_count': 0,
        'photos_count': 0,
        'remix_score': 0,
        'dashboard_visibility': False,
        'is_verified': False,
    }
    info = extract(json.dumps(body))
    assert info.get('picsart_username') == 'adam'
    assert info.get('fullname') == 'Adam'
    assert info.get('picsart_id') == '184924161000102'
    assert info.get('image') == 'https://example.com/p.jpg'
    assert info.get('follower_count') == '3'
    assert info.get('following_count') == '5'


def test_imgur_api_adds_canonical_profile_avatar_url():
    """
    Verifies **Imgur API** field `imgur_profile_avatar_url`: stable `https://imgur.com/user/{user}/avatar`
    alongside CDN `avatar_url` (per improvement log).

    **Check:** helper `imgur_profile_avatar_url` matches the same string the scheme emits.
    """
    body = {
        'id': 123,
        'username': 'sardelkin',
        'bio': '',
        'reputation_count': 1,
        'reputation_name': 'Neutral',
        'avatar_url': 'https://i.imgur.com/x.png',
        'created_at': '2010-01-01',
    }
    info = extract(json.dumps(body))
    assert info.get('imgur_username') == 'sardelkin'
    assert info.get('imgur_profile_avatar_url') == imgur_profile_avatar_url('sardelkin')
    assert info.get('imgur_profile_avatar_url') == 'https://imgur.com/user/sardelkin/avatar'


def test_strip_invalid_gravatar_urls_clears_bare_homepage():
    """
    Verifies **StripInvalidGravatarUrls**: values that are only `https://gravatar.com` (no `/avatar/hash`)
    are cleared from `gravatar_url` and `image` so downstream tools do not treat them as images.

    **Check:** bare root URL is detected; valid avatar URLs are untouched.
    """
    assert is_bare_gravatar_root_url('https://gravatar.com') is True
    assert is_bare_gravatar_root_url('https://www.gravatar.com/') is True
    assert is_bare_gravatar_root_url('https://secure.gravatar.com/avatar/abc') is False

    cleared = StripInvalidGravatarUrls(
        {'gravatar_url': 'https://gravatar.com', 'image': 'https://www.gravatar.com'}
    ).process()
    assert cleared.get('gravatar_url') == ''
    assert cleared.get('image') == ''

    untouched = StripInvalidGravatarUrls(
        {'image': 'https://secure.gravatar.com/avatar/' + '0' * 32}
    ).process()
    assert untouched == {}


def test_gravatar_postprocessor_requires_md5_hash():
    """
    Verifies **Gravatar** postprocessor only emits `gravatar_url` / hash fields when the image URL
    contains a valid 32-char hex MD5 in `/avatar/{hash}` (avoids bogus homepage-derived output).

    **Check:** `is_valid_gravatar_email_hash` gates emission; hash helper consistency.
    """
    assert is_valid_gravatar_email_hash('0' * 32) is True
    assert is_valid_gravatar_email_hash('gg' * 16) is False

    good = Gravatar(
        {'username': 'me', 'image': 'https://www.gravatar.com/avatar/' + 'a' * 32 + '?d=retro'}
    ).process()
    assert good.get('gravatar_email_md5_hash') == 'a' * 32
    assert 'gravatar.com' in good.get('gravatar_url', '')

    bad = Gravatar({'username': 'me', 'image': 'https://gravatar.com'}).process()
    assert bad == {}


def test_twitchtracker_embedded_channel_script():
    """TwitchTracker: `window.channel` JS literal with id, login, created_at."""
    html = """<!DOCTYPE html><html><head>
<meta property="og:site_name" content="TwitchTracker">
</head><body>
<script>\n\t\twindow.channel = {\n\t\t\tid: 37402112,\n\t\t\tname: 'shroud',\n\t\t\tcreated_at: '2012-11-03'\n\t\t}\n\t</script>
</body></html>"""
    info = extract(html)
    assert info.get('twitch_channel_id') == '37402112'
    assert info.get('twitch_username') == 'shroud'
    assert info.get('created_at') == '2012-11-03'


def test_chess_com_pub_api_json():
    """Chess.com API: public `/pub/player/{user}` JSON (optional mutate from /member/)."""
    body = (
        '{"avatar":"https://images.chesscomfiles.com/uploads/v1/user/15448422.x.png",'
        '"player_id":15448422,"username":"hikaru","name":"Hikaru Nakamura","title":"GM",'
        '"followers":100,"country":"https://api.chess.com/pub/country/US",'
        '"location":"Florida","last_online":1774140579,"joined":1389043258,'
        '"status":"premium","is_streamer":true,"verified":false,"twitch_url":"https://twitch.tv/gmhikaru"}'
    )
    info = extract(body)
    assert info.get('chess_user_id') == '15448422'
    assert info.get('username') == 'hikaru'
    assert info.get('fullname') == 'Hikaru Nakamura'
    assert info.get('country_code') == 'US'
    assert info.get('follower_count') == '100'
    assert info.get('is_verified') == 'False'
    assert info.get('created_at')
    assert info.get('latest_activity_at')


def test_codewars_api_json():
    """Codewars API: public `/api/v1/users/{user}` JSON (real live response for `soxoj`).

    **Check:** `uid` (hex id), `username`, `honor`, `leaderboard_position`, `rank`,
    `rank_score`, `languages` (sorted keys of `ranks.languages`), and
    `challenges_completed` are extracted. The real API returns no avatar or join date,
    so the scheme must not invent those fields.
    """
    body = (
        '{"id":"59c27ad8aeb28451ce0000d2","username":"soxoj","name":"","honor":149,'
        '"clan":"","leaderboardPosition":631632,"skills":[],'
        '"ranks":{"overall":{"rank":-6,"name":"6 kyu","color":"yellow","score":135},'
        '"languages":{"python":{"rank":-6,"name":"6 kyu","color":"yellow","score":135}}},'
        '"codeChallenges":{"totalAuthored":0,"totalCompleted":12}}'
    )
    info = extract(body)
    assert info.get('uid') == '59c27ad8aeb28451ce0000d2'
    assert info.get('username') == 'soxoj'
    assert info.get('fullname') is None  # empty `name` must not become an empty fullname
    assert info.get('honor') == '149'
    assert info.get('leaderboard_position') == '631632'
    assert info.get('rank') == '6 kyu'
    assert info.get('rank_score') == '135'
    assert info.get('languages') == "['python']"
    assert info.get('challenges_completed') == '12'
    assert 'image' not in info  # API has no avatar; scheme must not fabricate one


def test_minds_channel_api_json():
    """Minds API: public `/api/v1/channel/{user}` JSON (real live response for `mark`).

    **Check:** the `{"channel": {...}}` envelope is unwrapped; `uid` (guid), `username`,
    `fullname`, `location` (city), `gender`, `website`, `created_at` (unix→date), a derived
    `image` URL, and `social_links` (values from `social_profiles`) are extracted. Empty
    strings and `website:false` must resolve to absent fields, not blanks.
    """
    body = (
        '{"status":"success","channel":{"guid":"100000000000000063","type":"user",'
        '"time_created":"1348141290","name":"Mark Harding","username":"mark","language":"en",'
        '"icontime":"1771583437","banned":"no","website":"minds.com/mark","briefdescription":"",'
        '"gender":"male","city":"Preston, England, United Kingdom","boostProPlus":false,'
        '"verified":true,"social_profiles":['
        '{"key":"instagram","value":"instagram.com/mark.e.harding"},'
        '{"key":"github","value":"github.com/markharding"}]}}'
    )
    info = extract(body)
    assert info.get('uid') == '100000000000000063'
    assert info.get('username') == 'mark'
    assert info.get('fullname') == 'Mark Harding'
    assert info.get('location') == 'Preston, England, United Kingdom'
    assert info.get('gender') == 'male'
    assert info.get('website') == 'minds.com/mark'
    assert info.get('is_verified') == 'True'
    assert info.get('created_at')  # unix 1348141290 → formatted date
    assert info.get('image') == 'https://www.minds.com/icon/100000000000000063/large/1771583437'
    assert info.get('social_links') == "['instagram.com/mark.e.harding', 'github.com/markharding']"
    assert 'bio' not in info  # empty briefdescription must not become a blank bio


def test_hackernoon_profiles_api_json():
    """HackerNoon API: Firebase `profilesApi/?handle={h}` JSON (real live shape for `natasha`).

    **Check:** the `{"profile": {...}}` envelope is unwrapped; `uid`, `username` (handle),
    `fullname`, `bio`, `email`, `image`, and `social_accounts` (platform:value pairs) are
    extracted. The case-mismatch `{"redirect": {...}}` response must NOT match this scheme.
    """
    body = (
        '{"profile":{"id":"HrzvBX6xNSVZBKImURJl23sRwcQ2",'
        '"avatar":"https://cdn.hackernoon.com/images/avatars/HrzvBX6xNSVZBKImURJl23sRwcQ2.jpg",'
        '"displayName":"Natasha Nel","handle":"natasha","email":"natasha@hackernoon.com",'
        '"bio":"VP of Growth Marketing","allowSubscribers":true,'
        '"socialMedia":{"github":"hackernoon","twitter":"natashanoon",'
        '"instagram":"https://www.instagram.com/hackernoon/?hl=en"}},'
        '"profileStories":[],"annotations":[]}'
    )
    info = extract(body)
    assert info.get('uid') == 'HrzvBX6xNSVZBKImURJl23sRwcQ2'
    assert info.get('username') == 'natasha'
    assert info.get('fullname') == 'Natasha Nel'
    assert info.get('bio') == 'VP of Growth Marketing'
    assert info.get('email') == 'natasha@hackernoon.com'
    assert info.get('image') == 'https://cdn.hackernoon.com/images/avatars/HrzvBX6xNSVZBKImURJl23sRwcQ2.jpg'
    assert info.get('social_accounts') == (
        "['github:hackernoon', 'twitter:natashanoon', "
        "'instagram:https://www.instagram.com/hackernoon/?hl=en']"
    )
    # Case-mismatch redirect response must not be parsed as a profile.
    redirect = extract('{"redirect":{"destination":"https://hackernoon.com/u/David","permanent":true}}')
    assert redirect.get('_extractor') != 'HackerNoon API'


def test_polar_org_api_json():
    """Polar API: `/v1/customer-portal/organizations/{slug}` JSON (real live shape, `polarsource`)."""
    body = (
        '{"organization":{"created_at":"2023-04-20T10:01:30.383594Z",'
        '"id":"058c300d-c2b1-4d2c-9aa7-e3644e93140c","name":"Polarsource","slug":"polarsource",'
        '"avatar_url":"https://avatars.githubusercontent.com/u/105373340?v=4",'
        '"bio":"Building a creator platform for developers","company":null,"blog":"https://polar.sh",'
        '"location":"Sweden","twitter_username":"polar_sh","email":"support@polar.sh",'
        '"website":"https://polar.sh","socials":[]}}'
    )
    info = extract(body)
    assert info.get('uid') == '058c300d-c2b1-4d2c-9aa7-e3644e93140c'
    assert info.get('username') == 'polarsource'
    assert info.get('location') == 'Sweden'
    assert info.get('twitter_username') == 'polar_sh'
    assert info.get('email') == 'support@polar.sh'
    assert info.get('github_uid') == '105373340'  # derived from avatar_url → GitHub API crosslink
    assert 'company' not in info  # null company must not appear


def test_thanks_dev_api_json():
    """thanks.dev API: `/v1/profile/gh/{user}` JSON. Shadow profiles (name==`gh/{h}`) drop fullname."""
    real = extract(
        '{"git":{"ghgl":"gh","name":"frontendmasters"},"name":"Frontend Masters",'
        '"bio":"The training platform","resume":null,"url":"https://FrontendMasters.com",'
        '"li":null,"tw":"frontendmasters","dc":null,"bs":null,"isUser":false,"isTdUser":true}'
    )
    assert real.get('github_username') == 'frontendmasters'
    assert real.get('fullname') == 'Frontend Masters'
    assert real.get('twitter_username') == 'frontendmasters'
    assert real.get('website') == 'https://FrontendMasters.com'
    assert real.get('is_thanks_dev_user') == 'True'
    # shadow profile: name is the literal `gh/torvalds` → must not surface as fullname
    shadow = extract(
        '{"git":{"ghgl":"gh","name":"torvalds"},"name":"gh/torvalds","bio":null,"resume":null,'
        '"url":null,"li":null,"tw":null,"dc":null,"bs":null,"isUser":true,"isTdUser":false}'
    )
    assert shadow.get('github_username') == 'torvalds'
    assert 'fullname' not in shadow


def test_matrix_profile_api_json():
    """Matrix federated profile API: displayname + mxc→https avatar transform."""
    info = extract('{"displayname":"Soxoj","avatar_url":"mxc://matrix.org/EpRcnMLuQJfRavlJsqImrAei"}')
    assert info.get('fullname') == 'Soxoj'
    assert info.get('image') == (
        'https://matrix-client.matrix.org/_matrix/client/v1/media/thumbnail/'
        'matrix.org/EpRcnMLuQJfRavlJsqImrAei?width=512&height=512&method=scale'
    )


def test_substack_public_profile_extended_fields():
    """Substack public profile API: created_at, twitter, and publication crosslinks (real `soxoj`)."""
    body = (
        '{"id":131049184,"handle":"soxoj","name":"Soxoj","bio":"x",'
        '"photo_url":"https://example/a.jpg","profile_set_up_at":"2023-02-24T08:50:43.727Z",'
        '"twitterAccount":{"screen_name":"Sox0j","twitter_id":"1031199669488177153"},'
        '"publicationUsers":[{"publication":{"subdomain":"soxoj","name":"Soxoj on Substack",'
        '"hero_text":"OSINT mindset, methods, and tools"}}]}'
    )
    info = extract(body)
    assert info.get('username') == 'soxoj'
    assert info.get('created_at') == '2023-02-24T08:50:43.727Z'
    assert info.get('twitter_username') == 'Sox0j'
    assert info.get('twitter_id') == '1031199669488177153'
    assert info.get('publication_subdomain') == 'soxoj'
    assert info.get('publication_name') == 'Soxoj on Substack'
    assert info.get('publication_bio') == 'OSINT mindset, methods, and tools'


def test_youtube_ytinitialdata_about_and_socials():
    """YouTube ytInitialData (moved from plugin): channel metadata + redirect-derived social
    usernames + aboutChannelViewModel fields (country/joined/subscriber/views/videos).

    **Check:** the scheme that wins is the merged main-repo `YouTube ytInitialData` (not a
    shadowed duplicate), an instagram redirect URL resolves to a handle, and the about-panel
    string fields land on `location`, `created_at`, `follower_count`, `views_count`, `videos_count`.
    """
    yt = {
        'metadata': {'channelMetadataRenderer': {
            'externalId': 'UCX6OQ3DkcsbYNE6H8uQQuVA',
            'title': 'MrBeast',
            'description': 'SUBSCRIBE FOR A COOKIE!',
            'vanityChannelUrl': 'http://www.youtube.com/@MrBeast',
            'avatar': {'thumbnails': [{'url': 'https://yt3.ggpht.com/av.jpg'}]},
            'isFamilySafe': True,
            'facebookProfileId': 'MrBeast6000',  # non-numeric → facebook_username, not facebook_id
        }},
        'onResponseReceivedEndpoints': [{'panel': {'aboutChannelViewModel': {
            'country': 'United States',
            'joinedDateText': {'content': 'Joined Feb 19, 2012'},
            'subscriberCountText': '508M subscribers',
            'viewCountText': '133,717,699,032 views',
            'videoCountText': '993 videos',
        }}}],
        'redirectLink': 'https://www.youtube.com/redirect?q=https%3A%2F%2Fwww.instagram.com%2Fmrbeast%2F',
    }
    html = 'var ytInitialData = ' + json.dumps(yt) + ';</script>'
    info = extract(html)
    assert info.get('_extractor') == 'YouTube ytInitialData'
    assert info.get('youtube_channel_id') == 'UCX6OQ3DkcsbYNE6H8uQQuVA'
    assert info.get('fullname') == 'MrBeast'
    assert info.get('location') == 'United States'
    # "Joined Feb 19, 2012" → strip prefix → a date postprocessor normalises it to ISO.
    assert info.get('created_at') == '2012-02-19 00:00:00 UTC'
    assert info.get('follower_count') == '508M subscribers'
    assert info.get('views_count') == '133,717,699,032 views'
    assert info.get('videos_count') == '993 videos'
    assert info.get('instagram_username') == 'mrbeast'  # decoded from youtube.com/redirect?q=
    assert info.get('facebook_username') == 'MrBeast6000'
    assert 'facebook_id' not in info  # non-numeric profile id must not become facebook_id


def test_roblox_user_api_json():
    """Roblox GET /v1/users/{id} envelope."""
    body = (
        '{"description":"x","created":"2006-02-27T21:06:40.3Z","isBanned":false,'
        '"externalAppDisplayName":null,"hasVerifiedBadge":true,"id":1,'
        '"name":"Roblox","displayName":"Roblox"}'
    )
    info = extract(body)
    assert info.get('roblox_user_id') == '1'
    assert info.get('username') == 'Roblox'
    assert info.get('is_verified') == 'True'


def test_roblox_username_lookup_api_json():
    """Roblox POST /v1/usernames/users first user object."""
    body = (
        '{"data":[{"requestedUsername":"Roblox","hasVerifiedBadge":true,"id":1,'
        '"name":"Roblox","displayName":"Roblox"}]}'
    )
    info = extract(body)
    assert info.get('roblox_user_id') == '1'
    assert info.get('username') == 'Roblox'


def test_myanimelist_profile_regex():
    """MAL profile: numeric uid from analytics param + username from og:url."""
    html = """<!DOCTYPE html><html><head>
<meta property="og:url" content="https://myanimelist.net/profile/Xinil">
</head><body>
<div class="user-profile">
<a href="#" data-ga-click-param="uid:1" title="msg"><i></i></a>
</div></body></html>"""
    info = extract(html)
    assert info.get('mal_username') == 'Xinil'
    assert info.get('mal_uid') == '1'


def test_xvideos_profile_full():
    """XVideos profile: extract user id, username, display name, gender, country, subscribers, signed up."""
    html = (
        '<html lang="en" class="xv-responsive"><body>'
        '<a href="https://www.xvideos.com/profiles/soxoj">p</a>'
        '<script>"id_user":613639497,"username":"soxoj","display":"Soxoj","profile_picture_small":"","profile_picture":"","sex":"Man","url":"/profiles/soxoj"</script>'
        '<div class="col-sm-4 col-xs-12 pfinfo-col" id="pfinfo-col-col1">'
        '<p id="pinfo-sex"><strong>Gender:</strong> <span>Man</span></p>'
        '<p id="pinfo-country"><strong>Country:</strong> <span>Honduras</span></p>'
        '<p id="pinfo-profile-hits"><strong>Profile hits:</strong> <span>1,768</span></p>'
        '<p id="pinfo-subscribers"><strong>Subscribers:</strong> <span>4</span></p>'
        '<p id="pinfo-signedup"><strong>Signed up:</strong> <span>July 16, 2022 (1,354 days ago)</span></p>'
        '</div></body></html>'
    )
    info = extract(html)
    assert info.get('uid') == '613639497'
    assert info.get('username') == 'soxoj'
    assert info.get('fullname') == 'Soxoj'
    assert info.get('gender') == 'Man'
    assert info.get('country') == 'Honduras'
    assert info.get('profile_hits') == '1,768'
    assert info.get('follower_count') == '4'
    assert info.get('created_at') == '2022-07-16 00:00:00 UTC'


def test_lnk_bio_next_data_fixture():
    """lnk.bio-style __NEXT_DATA__ with pageProps.profile (fixture; live HTML may differ)."""
    next_data = {
        'props': {
            'pageProps': {
                'profile': {
                    'username': 'fixture',
                    'displayName': 'Fixture User',
                    'bio': 'Hello',
                    'avatar': 'https://example.com/a.png',
                    'links': [{'title': 'Site', 'url': 'https://example.org'}],
                }
            }
        }
    }
    html = (
        '<!DOCTYPE html><html><head><title>lnk.bio</title></head><body>'
        '<link rel="canonical" href="https://lnk.bio/fixture" />'
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(next_data)
        + '</script>mention lnk.bio in body for flags</body></html>'
    )
    info = extract(html)
    assert info.get('username') == 'fixture'
    assert info.get('fullname') == 'Fixture User'
    assert 'example.org' in info.get('links', '')


def test_buzzfeed_next_data_extraction():
    """
    Verifies the **BuzzFeed** scheme matches pages containing `buzzfeed.com`
    and `__NEXT_DATA__`, extracts user profile fields from the embedded JSON,
    and correctly constructs image URLs.

    **Check:** `uuid`, `id`, `fullname`, `username`, `bio`, `posts_count`,
    `is_community_user`, `is_deleted`, `image`, and `social_links` are present.
    """
    next_data = {
        'props': {
            'pageProps': {
                'user_uuid': 'abc-123-def',
                'user': {
                    'id': 99999,
                    'displayName': 'TestUser',
                    'username': 'testuser',
                    'bio': 'Hello world',
                    'memberSince': 1261100829,
                    'isCommunityUser': True,
                    'deleted': False,
                    'social': [{'name': 'twitter', 'url': 'https://twitter.com/test'}],
                    'image': '/static/user_images/test.jpg',
                    'headerImage': '/static/enhanced/test_wide.jpg',
                },
                'buzz_count': 5,
            }
        },
        'page': '/[username]',
        'query': {'username': 'testuser'},
        'buildId': 'fixture123',
    }
    html = (
        '<!DOCTYPE html><html><head>'
        '<link rel="canonical" href="https://www.buzzfeed.com/testuser">'
        '</head><body>'
        '<div>Content from buzzfeed.com</div>'
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(next_data)
        + '</script></body></html>'
    )
    info = extract(html)
    assert info.get('uuid') == 'abc-123-def'
    assert info.get('id') == '99999'
    assert info.get('fullname') == 'TestUser'
    assert info.get('username') == 'testuser'
    assert info.get('bio') == 'Hello world'
    assert info.get('posts_count') == '5'
    assert info.get('is_community_user') == 'True'
    assert info.get('is_deleted') == 'False'
    assert 'buzzfeed-static' in info.get('image', '')
    assert 'twitter.com/test' in info.get('social_links', '')


def test_fandom_mediawiki_api_json():
    """Fandom MediaWiki API: extract userid and canonical username from user query response."""
    body = json.dumps({
        "batchcomplete": "",
        "query": {
            "users": [
                {"userid": 22693, "name": "Red"}
            ]
        }
    })
    info = extract(body)
    assert info.get('uid') == '22693'
    assert info.get('username') == 'Red'


def test_fandom_mediawiki_api_missing_user():
    """Fandom MediaWiki API: missing user has no userid — scheme should still match but yield empty uid."""
    body = json.dumps({
        "batchcomplete": "",
        "query": {
            "users": [
                {"name": "NonexistentUser12345", "missing": ""}
            ]
        }
    })
    info = extract(body)
    # missing user has no userid → uid should be absent or empty
    assert info.get('username') == 'NonexistentUser12345'
    assert not info.get('uid')


def test_substack_public_profile_api_json():
    """Substack public profile API: extract user fields from JSON response."""
    body = json.dumps({
        "id": 188506911,
        "name": "Philip",
        "handle": "user23",
        "photo_url": "https://substack-post-media.s3.amazonaws.com/photo.jpg",
        "bio": "Been Internettin' since 1997",
        "profile_set_up_at": "2023-12-11T03:04:51.141Z",
    })
    info = extract(body)
    assert info.get('uid') == '188506911'
    assert info.get('username') == 'user23'
    assert info.get('fullname') == 'Philip'
    assert info.get('bio') == "Been Internettin' since 1997"
    assert 'substack-post-media' in info.get('image', '')


def test_hashnode_graphql_api_json():
    """hashnode GraphQL API: extract username and fullname from GraphQL response."""
    body = json.dumps({
        "data": {
            "user": {
                "name": "Melwin D'Almeida",
                "username": "melwinalm",
                "tagline": "Cloud enthusiast",
                "dateJoined": "2018-02-18T15:24:29.694Z",
                "socialMediaLinks": {
                    "twitter": "https://twitter.com/melwinalm",
                    "github": "",
                    "linkedin": None,
                    "website": ""
                }
            }
        }
    })
    info = extract(body)
    assert info.get('username') == 'melwinalm'
    assert info.get('fullname') == "Melwin D'Almeida"
    assert info.get('bio') == 'Cloud enthusiast'
    assert info.get('created_at') == '2018-02-18T15:24:29.694Z'
    assert info.get('twitter_username') == 'melwinalm'


def test_hashnode_graphql_api_null_user():
    """hashnode GraphQL API: null user (unclaimed) should yield empty result."""
    body = json.dumps({
        "data": {
            "user": None,
            "dateJoined": None,
            "socialMediaLinks": None
        }
    })
    info = extract(body)
    assert not info.get('username')
    assert not info.get('fullname')


def test_rarible_api_json():
    """Rarible API: extract user ownership info from marketplace API response."""
    body = json.dumps({
        "createDate": "2020-07-21T15:18:51.758+00:00",
        "id": "blue",
        "owner": "0x0000000000000000000000000000000000000000",
        "ref": "0x65d472172e4933aa4ddb995cf4ca8bef72a46576",
        "type": "USER",
        "version": 0,
    })
    info = extract(body)
    assert info.get('rarible_id') == 'blue'
    assert info.get('rarible_owner') == '0x0000000000000000000000000000000000000000'
    assert info.get('rarible_ref') == '0x65d472172e4933aa4ddb995cf4ca8bef72a46576'
    assert info.get('rarible_type') == 'USER'
    assert info.get('created_at') == '2020-07-21T15:18:51.758+00:00'


def test_cssbattle_next_data_fixture():
    """CSSBattle: extract player stats from __NEXT_DATA__ embedded JSON."""
    next_data = {
        "props": {
            "pageProps": {
                "player": {
                    "id": "8wBrf63WLOOv8JuCeknfYk7t94B3",
                    "username": "beo",
                    "gamesPlayed": 55,
                    "score": 1234.56,
                }
            }
        }
    }
    html = (
        '<!DOCTYPE html><html><head><title>CSSBattle</title></head><body>'
        '<link rel="canonical" href="https://cssbattle.dev/player/beo" />'
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(next_data)
        + '</script>cssbattle.dev footer</body></html>'
    )
    info = extract(html)
    assert info.get('cssbattle_id') == '8wBrf63WLOOv8JuCeknfYk7t94B3'
    assert info.get('cssbattle_username') == 'beo'
    assert info.get('cssbattle_games_played') == '55'
    assert info.get('cssbattle_score') == '1234.56'


def test_max_ru_sveltekit_profile():
    """Max (max.ru): extract channel info from SvelteKit hydration JS object."""
    html = (
        '<!DOCTYPE html><html><head></head><body>'
        '<script>__sveltekit_start({data:[null,{type:"data",data:'
        '{channel:{title:"Ирина Волк",description:"Канал генерал-лейтенанта",'
        'icon:"https://i.oneme.ru/i?r=abc123",participantsCount:15599}}'
        ',uses:{url:1}},null]})</script>'
        '</body></html>'
    )
    info = extract(html)
    assert info.get('max_title') == 'Ирина Волк'
    assert info.get('max_description') == 'Канал генерал-лейтенанта'
    assert 'oneme.ru' in info.get('max_icon', '')
    assert info.get('max_participants_count') == '15599'


def test_periscope_profile_extraction():
    """Periscope (pscp.tv): extract user profile fields from data-store JSON."""
    user_data = {
        'id': 'abc123XYZ',
        'created_at': '2016-04-10T18:22:05.411012300+00:00',
        'username': 'Polina_Zograf',
        'display_name': '🌸',
        'description': 'Travel blogger',
        'n_followers': 1200,
        'n_following': 85,
        'n_hearts': 54320,
        'n_broadcasts': 42,
        'is_beta_user': False,
        'is_employee': False,
        'isVerified': False,
        'is_twitter_verified': True,
        'twitterUserId': '78901234',
        'twitter_screen_name': 'polina_z',
        'profile_image_urls': [
            {'url': 'https://pbs.twimg.com/profile_images/123/photo.jpg', 'width': 128, 'height': 128}
        ],
    }
    data_store = {
        'canonicalPeriscopeUrl': 'https://www.pscp.tv/Polina_Zograf',
        'UserCache': {
            'users': {
                'abc123XYZ': {
                    'user': user_data
                }
            }
        },
    }
    escaped = json.dumps(data_store).replace('"', '&quot;')
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:site_name" content="Periscope"/>'
        '<link rel="alternate" href="pscp://user/abc123XYZ"/>'
        '</head><body>'
        '<div data-store="' + escaped + '"><div id="PageView">'
        '<div>page content</div>'
        '</div></div></body></html>'
    )
    info = extract(html)
    assert info.get('id') == 'abc123XYZ'
    assert info.get('periscope_username') == 'Polina_Zograf'
    assert info.get('fullname') == '🌸'
    assert info.get('bio') == 'Travel blogger'
    assert info.get('image') == 'https://pbs.twimg.com/profile_images/123/photo.jpg'
    assert info.get('follower_count') == '1200'
    assert info.get('following_count') == '85'
    assert info.get('hearts_count') == '54320'
    assert info.get('broadcasts_count') == '42'
    assert info.get('is_beta_user') == 'False'
    assert info.get('is_employee') == 'False'
    assert info.get('is_verified') == 'False'
    assert info.get('is_twitter_verified') == 'True'
    assert info.get('twitter_uid') == '78901234'
    assert info.get('twitter_screen_name') == 'polina_z'
    assert info.get('created_at') == '2016-04-10T18:22:05.411012300+00:00'


def test_bluesky_api_json():
    """Bluesky API: extract profile fields from public AT Protocol API response."""
    body = json.dumps({
        "did": "did:plc:oky5czdrnfjpqslsw2a5iclo",
        "handle": "jay.bsky.team",
        "displayName": "Jay",
        "description": "Building the AT Protocol",
        "avatar": "https://cdn.bsky.app/img/avatar/plain/did:plc:oky5czdrnfjpqslsw2a5iclo/photo.jpg",
        "banner": "https://cdn.bsky.app/img/banner/plain/did:plc:oky5czdrnfjpqslsw2a5iclo/banner.jpg",
        "followersCount": 50000,
        "followsCount": 200,
        "postsCount": 1500,
        "createdAt": "2022-11-17T06:31:40.296Z",
        "labels": [],
    })
    info = extract(body)
    assert info.get('uid') == 'did:plc:oky5czdrnfjpqslsw2a5iclo'
    assert info.get('username') == 'jay.bsky.team'  # custom domain, no .bsky.social suffix
    assert info.get('fullname') == 'Jay'
    assert info.get('bio') == 'Building the AT Protocol'
    assert 'cdn.bsky.app' in info.get('image', '')
    assert info.get('follower_count') == '50000'
    assert info.get('following_count') == '200'
    assert info.get('posts_count') == '1500'
    assert info.get('created_at') == '2022-11-17T06:31:40.296Z'


def test_bluesky_api_strips_bsky_social_suffix():
    """Bluesky API: .bsky.social suffix is stripped from handle."""
    body = json.dumps({
        "did": "did:plc:abc123",
        "handle": "alice.bsky.social",
        "displayName": "Alice",
        "followersCount": 10,
        "followsCount": 5,
        "postsCount": 1,
    })
    info = extract(body)
    assert info.get('username') == 'alice'


def test_scratch_api_json():
    """Scratch API: extract user profile from scratch.mit.edu API response."""
    body = json.dumps({
        "id": 1882674,
        "username": "griffpatch",
        "scratchteam": False,
        "history": {"joined": "2012-11-20T16:43:15.000Z"},
        "profile": {
            "id": None,
            "images": {"90x90": "https://cdn2.scratch.mit.edu/get_image/user/1882674_90x90.png"},
            "status": "I make games!",
            "bio": "Hi, I'm griffpatch. I love coding in Scratch!",
            "country": "United Kingdom",
        },
    })
    info = extract(body)
    assert info.get('uid') == '1882674'
    assert info.get('username') == 'griffpatch'
    assert info.get('bio') == "Hi, I'm griffpatch. I love coding in Scratch!"
    assert info.get('status') == 'I make games!'
    assert info.get('country') == 'United Kingdom'
    assert 'scratch.mit.edu' in info.get('image', '')
    assert info.get('created_at') == '2012-11-20T16:43:15.000Z'
    assert info.get('is_scratchteam') == 'False'


def test_wikipedia_user_api_json():
    """Wikipedia user API: extract user info from MediaWiki user query with editcount."""
    body = json.dumps({
        "batchcomplete": "",
        "query": {
            "users": [{
                "userid": 24920566,
                "name": "Example",
                "editcount": 42,
                "registration": "2015-04-24T07:00:51Z",
                "gender": "male",
            }]
        }
    })
    info = extract(body)
    assert info.get('uid') == '24920566'
    assert info.get('username') == 'Example'
    assert info.get('edit_count') == '42'
    assert info.get('created_at') == '2015-04-24T07:00:51Z'
    assert info.get('gender') == 'male'


def test_dailymotion_api_json():
    """DailyMotion API: extract user profile from API response."""
    body = json.dumps({
        "id": "x23k8rz",
        "username": "cnn",
        "screenname": "CNN",
        "description": "CNN breaking news",
        "avatar_720_url": "https://s2.dmcdn.net/d/5000002HraHpp/720x720",
        "cover_250_url": "https://s2.dmcdn.net/d/cover/250",
        "followers_total": 150000,
        "following_total": 50,
        "videos_total": 3200,
        "country": "US",
        "created_time": 1518206261,
        "verified": True,
        "url": "https://www.dailymotion.com/cnn",
    })
    info = extract(body)
    assert info.get('uid') == 'x23k8rz'
    assert info.get('username') == 'cnn'
    assert info.get('fullname') == 'CNN'
    assert info.get('bio') == 'CNN breaking news'
    assert 'dmcdn.net' in info.get('image', '')
    assert info.get('follower_count') == '150000'
    assert info.get('videos_count') == '3200'
    assert info.get('country') == 'US'
    assert info.get('is_verified') == 'True'


def test_slideshare_next_data_user():
    """SlideShare: extract user from __NEXT_DATA__ embedded JSON."""
    next_data = {
        "props": {
            "pageProps": {
                "user": {
                    "id": 133494799,
                    "name": "Reed Hastings",
                    "login": "ReedHastings",
                    "photo": "https://public.slidesharecdn.com/v2/images/profile-picture.png",
                    "description": "Co-founder of Netflix",
                    "slideshowCount": 12,
                    "followersCount": 500,
                    "followingCount": 10,
                    "city": "San Francisco",
                    "country": "US",
                    "organization": "Netflix",
                    "occupation": "CEO",
                    "url": "https://netflix.com",
                    "suspended": False,
                    "isOrganization": False,
                }
            }
        }
    }
    html = (
        '<!DOCTYPE html><html><head></head><body>'
        '<link rel="stylesheet" href="https://public.slidesharecdn.com/v2/css/main.css">'
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(next_data)
        + '</script></body></html>'
    )
    info = extract(html)
    assert info.get('uid') == '133494799'
    assert info.get('fullname') == 'Reed Hastings'
    assert info.get('username') == 'ReedHastings'
    assert info.get('bio') == 'Co-founder of Netflix'
    assert info.get('slideshow_count') == '12'
    assert info.get('follower_count') == '500'
    assert info.get('organization') == 'Netflix'
    assert info.get('website') == 'https://netflix.com'
    assert info.get('is_suspended') == 'False'


def test_wordpress_org_profile():
    """WordPress.org Profile: extract username and fullname from og:title meta tag."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:title" content="WordPress (@wordpress) - WordPress user profile">'
        '<meta property="og:image" content="https://www.gravatar.com/avatar/834ffe?s=1024">'
        '<li id="user-member-since"><div>Member Since</div></li>'
        '<link rel="canonical" href="https://profiles.wordpress.org/wordpress/">'
        '</head><body></body></html>'
    )
    info = extract(html)
    assert info.get('fullname') == 'WordPress'
    assert info.get('username') == 'wordpress'
    assert 'gravatar.com' in info.get('image', '')


def test_weebly_js_vars():
    """Weebly: extract user_id and site_id from inline JS variables."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<link rel="stylesheet" href="https://cdn2.editmysite.com/css/main.css">'
        '</head><body>'
        '<script>com_currentSite = "183235046254098859"; com_userID = "125320777";</script>'
        '</body></html>'
    )
    info = extract(html)
    assert info.get('uid') == '125320777'
    assert info.get('weebly_site_id') == '183235046254098859'


def test_calendly_api_json():
    """Calendly: extract booking profile fields from API JSON response."""
    body = json.dumps({
        "id": 7723,
        "avatar_url": None,
        "description": "Welcome to my scheduling page.",
        "is_landing_page": False,
        "locale": "en",
        "logo_url": None,
        "name": "admin google",
        "organization_uuid": "DFBBGBHGHUHT7RGG",
        "owner_type": "User",
        "owning_user": {"id": 8173, "uuid": "27f70b874abf8cd45edcdb092001661b"},
        "slug": "google",
        "timezone": "America/New_York",
        "unavailability_reason": None,
        "unbranded": False,
    })
    info = extract(body)
    assert info.get('uid') == '7723'
    assert info.get('fullname') == 'admin google'
    assert info.get('username') == 'google'
    assert info.get('bio') == 'Welcome to my scheduling page.'
    assert info.get('owner_uuid') == '27f70b874abf8cd45edcdb092001661b'
    assert info.get('organization_uuid') == 'DFBBGBHGHUHT7RGG'
    assert info.get('timezone') == 'America/New_York'


def test_google_play_developer():
    """Google Play Developer: extract developer name from og:title."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:title" content="Android Apps by Google LLC on Google Play">'
        '<script>AF_initDataCallback({key:"ds:3"});</script>'
        '<link rel="canonical" href="https://play.google.com/store/apps/developer?id=Google+LLC">'
        '</head><body></body></html>'
    )
    info = extract(html)
    assert info.get('developer_name') == 'Google LLC'


def test_amazon_author_page():
    """Amazon Author: extract author name, id and store id from inline JSON."""
    html = (
        '<!DOCTYPE html><html><head></head><body>'
        '<div data-a-page-id="stores/author/B000AQ3RBI">'
        '<script>var config = {"widgetType":"AuthorSubHeader","content":{"authorName":"Richard Dawkins"},'
        '"pageContext":{"authorId":"B000AQ3RBI","storeId":"b55aba37-be09-3e56-80fb-da9cda3c406b"'
        ',"pageDescription":"Follow Richard Dawkins"'
        ',"brandLogo":{"image":"https://m.media-amazon.com/images/I/41viH8VtXtL.jpg"}'
        '}};</script>'
        '</body></html>'
    )
    info = extract(html)
    assert info.get('author_name') == 'Richard Dawkins'
    assert info.get('author_id') == 'B000AQ3RBI'
    assert info.get('store_id') == 'b55aba37-be09-3e56-80fb-da9cda3c406b'


def test_stack_overflow_user_init():
    """Stack Overflow: extract userId and accountId from StackExchange.user.init call."""
    html = (
        '<!DOCTYPE html><html><head></head><body>'
        '<script>StackExchange.user.init({ userId: 22656, accountId: 11683 });</script>'
        '</body></html>'
    )
    info = extract(html)
    assert info.get('uid') == '22656'
    assert info.get('stack_exchange_uid') == '11683'


def test_linktree_updated_flags():
    """Linktree: verify updated flags work with current page format."""
    next_data = {
        "props": {
            "pageProps": {
                "account": {
                    "id": 12345,
                    "uuid": "6ba1b72b-4009-11eb-85b8-0a26086d88df",
                    "isActive": True,
                    "tier": "free",
                    "links": [{"url": "https://example.com"}],
                },
                "username": "testuser",
                "profilePictureUrl": "https://ugc.production.linktr.ee/pic.jpg",
                "isProfileVerified": True,
                "description": "My bio",
                "socialLinks": [{"type": "TWITTER", "url": "https://twitter.com/test"}],
            }
        }
    }
    html = (
        '<!DOCTYPE html><html><head></head><body>'
        '<link rel="canonical" href="https://linktr.ee/testuser">'
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(next_data)
        + '</script></body></html>'
    )
    info = extract(html)
    assert info.get('id') == '12345'
    assert info.get('username') == 'testuser'
    assert info.get('is_verified') == 'True'
    assert info.get('bio') == 'My bio'


def test_picsart_facebook_uid_from_photo():
    """Picsart API: extract facebook_uid from graph.facebook.com photo URL."""
    body = {
        'id': 100,
        'name': 'FbUser',
        'username': 'fbuser',
        'photo': 'https://graph.facebook.com/999888777/picture',
        'followers_count': 0,
        'following_count': 0,
        'likes_count': 0,
        'photos_count': 0,
        'remix_score': 0,
        'dashboard_visibility': False,
        'is_verified': False,
    }
    info = extract(json.dumps(body))
    assert info.get('facebook_uid') == '999888777'


def test_picsart_no_facebook_uid_when_no_graph_url():
    """Picsart API: facebook_uid is absent when photo is not a graph.facebook.com URL."""
    body = {
        'id': 101,
        'name': 'NormalUser',
        'username': 'normaluser',
        'photo': 'https://example.com/pic.jpg',
        'followers_count': 0,
        'following_count': 0,
        'likes_count': 0,
        'photos_count': 0,
        'remix_score': 0,
        'dashboard_visibility': False,
        'is_verified': False,
    }
    info = extract(json.dumps(body))
    assert not info.get('facebook_uid')


def test_habr_profile_extraction():
    """Habr: extract fullname, username, and profile URL from og meta tags."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:site_name" content="Хабр">'
        '<meta property="og:title" content="Иван Петров aka ipetrov  '
        '\n- "'
        '<meta property="og:url" content="https://habr.com/ru/users/ipetrov/">'
        '</head><body>habr.com/ru/users/ipetrov</body></html>'
    )
    info = extract(html)
    assert info.get('fullname') == 'Иван Петров'
    assert info.get('username') == 'ipetrov'
    assert 'habr.com/ru/users/ipetrov' in info.get('website', '')


def test_taplink_profile_extraction():
    """Taplink: extract image, fullname, and username from og meta tags."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:site_name" content="Taplink">'
        '<meta property="og:image" content="https://taplink.st/p/8/a/2/photo.jpg">'
        '<meta property="og:title" content="John Doe at Taplink">'
        '<meta property="og:url" content="https://taplink.cc/johndoe">'
        '</head><body>Welcome at Taplink</body></html>'
    )
    info = extract(html)
    assert info.get('fullname') == 'John Doe'
    assert info.get('username') == 'johndoe'
    assert 'taplink.st' in info.get('image', '')


def test_producthunt_profile_extraction():
    """Product Hunt: extract twitter_username and username from meta tags."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:site_name" content="Product Hunt">'
        '<meta property="og:type" content="profile">'
        '<meta name="twitter:creator" content="@rrhoover">'
        '<meta property="og:url" content="https://www.producthunt.com/@rrhoover">'
        '</head><body></body></html>'
    )
    info = extract(html)
    assert info.get('twitter_username') == 'rrhoover'
    assert info.get('username') == 'rrhoover'


def test_threads_profile_extraction():
    """Threads: meta tags for flags matching, info from json extracted from script tag"""
    """Reference page: https://www.threads.com/@zuck"""
    html = r'<meta property="al:android:package" content="com.instagram.barcelona"><meta property="og:title" content="Mark Zuckerberg (@zuck) • Threads, Say more">{"require":[["ScheduledServerJS","handle",null,[{"__bbox":{"require":[["RelayPrefetchedStreamCache","next",[],["adp_BarcelonaProfilePageDirectQueryRelayPreloader_6a6a63d9180cb2047895700",{"__bbox":{"complete":true,"result":{"data":{"user":{"profile_pic_url":"https:\/\/scontent-fco2-1.cdninstagram.com\/v\/t51.82787-19\/550174606_17925811725103224_8363667901743352243_n.jpg?stp=dst-jpg_s150x150_tt6&efg=eyJ2ZW5jb2RlX3RhZyI6InByb2ZpbGVfcGljLmRqYW5nby4xMDgwLmMyIn0&_nc_ht=scontent-fco2-1.cdninstagram.com&_nc_cat=1&_nc_oc=Q6cZ2gEMkOHv7XIrcuKP2rmVA8iNXre2bDiMGH0Eci0gVMu8JtdfnQUNlPW3MeJsWSKawY8&_nc_ohc=vLH8jAZMCqoQ7kNvwHd8fK9&_nc_gid=PjgEQH13NsOtLYe04DBt4w&edm=APs17CUBAAAA&ccb=7-5&oh=00_AQC1i1A8NvOTFZ8seAvZw-OcQK4K9w8N1EqSO12dxh55Bg&oe=6A7024FE&_nc_sid=10d13b","friendship_status":null,"has_onboarded_to_text_post_app":true,"pk":"63055343223","text_post_app_is_private":false,"username":"zuck","text_post_app_remove_mention_entrypoint":null,"text_app_custom_feeds":null,"gating":null,"follower_count":5682725,"profile_context_facepile_users":null,"text_post_app_public_views":null,"hd_profile_pic_versions":[{"height":320,"url":"https:\/\/scontent-fco2-1.cdninstagram.com\/v\/t51.82787-19\/550174606_17925811725103224_8363667901743352243_n.jpg?stp=dst-jpg_s320x320_tt6&efg=eyJ2ZW5jb2RlX3RhZyI6InByb2ZpbGVfcGljLmRqYW5nby4xMDgwLmMyIn0&_nc_ht=scontent-fco2-1.cdninstagram.com&_nc_cat=1&_nc_oc=Q6cZ2gEMkOHv7XIrcuKP2rmVA8iNXre2bDiMGH0Eci0gVMu8JtdfnQUNlPW3MeJsWSKawY8&_nc_ohc=vLH8jAZMCqoQ7kNvwHd8fK9&_nc_gid=PjgEQH13NsOtLYe04DBt4w&edm=APs17CUBAAAA&ccb=7-5&oh=00_AQAINYp3OxkUL11VXhgfJZ6aK7JN-NrY9HM02Wy6kbmuXw&oe=6A7024FE&_nc_sid=10d13b","width":320},{"height":640,"url":"https:\/\/scontent-fco2-1.cdninstagram.com\/v\/t51.82787-19\/550174606_17925811725103224_8363667901743352243_n.jpg?stp=dst-jpg_s640x640_tt6&efg=eyJ2ZW5jb2RlX3RhZyI6InByb2ZpbGVfcGljLmRqYW5nby4xMDgwLmMyIn0&_nc_ht=scontent-fco2-1.cdninstagram.com&_nc_cat=1&_nc_oc=Q6cZ2gEMkOHv7XIrcuKP2rmVA8iNXre2bDiMGH0Eci0gVMu8JtdfnQUNlPW3MeJsWSKawY8&_nc_ohc=vLH8jAZMCqoQ7kNvwHd8fK9&_nc_gid=PjgEQH13NsOtLYe04DBt4w&edm=APs17CUBAAAA&ccb=7-5&oh=00_AQBNhNuXAjZJ55KPO-_ZpvN2UXEnXQ8Ix3kChz5OMpxwUQ&oe=6A7024FE&_nc_sid=10d13b","width":640}],"is_verified":true,"biography":"Mostly superintelligence and MMA takes","text_app_biography":{"text_fragments":{"fragments":[{"fragment_type":"plaintext","link_fragment":null,"mention_fragment":null,"plaintext":"Mostly superintelligence and MMA takes","inline_sticker_fragment":null,"linkified_web_url":null,"linkified_in_app_url":null,"styling_info":null}]}},"full_name":"Mark Zuckerberg","bio_links":[],"profile_tags":{"edges":[{"node":{"display_name":"AI Threads","name":"aithreads","id":"18399895213044171","is_community":false,"tag_cluster_name":"aithreads"}},{"node":{"display_name":"UFC Threads","name":"ufcthreads","id":"18398478472015746","is_community":false,"tag_cluster_name":"UFCThreads"}},{"node":{"display_name":"AI","name":"ai","id":"18392111818029156","is_community":false,"tag_cluster_name":"AI"}},{"node":{"display_name":"MMA","name":"mma","id":"18400625521011745","is_community":false,"tag_cluster_name":"mma"}},{"node":{"display_name":"memes","name":"memes","id":"18402364270062744","is_community":false,"tag_cluster_name":"memes"}}]},"transparency_label":null,"show_text_post_app_badge":true,"platform_podcast_info":null,"platform_podcast_episode_info":null,"id":"63055343223"}},"extensions":{"is_final":true}},"sequence_number":0}}]],["CometResourceScheduler","registerHighPriHashes",null,[["y9umSZA","1DFRiCY"]]]],"phd2_indexes":":454"}},{"__bbox":null},{"__bbox":null}]]]}'
    
    info = extract(html)
    assert info.get('uid') == '63055343223'
    assert info.get('username') == 'zuck'
    assert info.get('fullname') == 'Mark Zuckerberg'
    assert info.get('bio') == "Mostly superintelligence and MMA takes"
    assert info.get('image', "").startswith('https://scontent')
    assert int(info.get('follower_count', 0)) == 5682725
    assert info.get('is_verified') == 'True'

def test_osu_extraction():
    """osu!: extract info from json in html attribute."""

    html = r"""
        <div class="osu-layout__section osu-layout__section--full">           
            <div class="js-react u-contents" data-initial-data="{&quot;achievements&quot;:[{&quot;achieved_count&quot;:1812,&quot;achieved_percent&quot;:6.352429195918838e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-mappersguild-07.png&quot;,&quot;id&quot;:265,&quot;name&quot;:&quot;Mappers' Guild Pack VII&quot;,&quot;grouping&quot;:&quot;Beatmap Challenge Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;all-packs-mappersguild-07&quot;,&quot;description&quot;:&quot;A new set of vibrant challenges to overcome.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Mappers' Guild VII pack, which require no difficulty reduction mods when submitting a score.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:951,&quot;achieved_percent&quot;:3.3339736011693236e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-mappersguild-08.png&quot;,&quot;id&quot;:266,&quot;name&quot;:&quot;Mappers' Guild Pack VIII&quot;,&quot;grouping&quot;:&quot;Beatmap Challenge Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;all-packs-mappersguild-08&quot;,&quot;description&quot;:&quot;Succeed with a chorus of voices.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Mappers' Guild VIII pack, which require no difficulty reduction mods when submitting a score.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2172,&quot;achieved_percent&quot;:7.614501221598077e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-muzz.png&quot;,&quot;id&quot;:284,&quot;name&quot;:&quot;MUZZ Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Challenge Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;all-packs-muzz&quot;,&quot;description&quot;:&quot;Break away from the endgame.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the MUZZ beatmap pack, which requires no difficulty reduction mods when submitting a score.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:584,&quot;achieved_percent&quot;:2.0473612861018772e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-mappersguild-09.png&quot;,&quot;id&quot;:267,&quot;name&quot;:&quot;Mappers' Guild Pack IX&quot;,&quot;grouping&quot;:&quot;Beatmap Challenge Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;all-packs-mappersguild-09&quot;,&quot;description&quot;:&quot;This is no subtle change.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Mappers' Guild IX pack, which require no difficulty reduction mods when submitting a score.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1437,&quot;achieved_percent&quot;:5.037770835836297e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-ariableyes.png&quot;,&quot;id&quot;:294,&quot;name&quot;:&quot;Ariabl'eyeS Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Challenge Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;all-packs-ariableyes&quot;,&quot;description&quot;:&quot;Command the mercurial skies.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Ariabl'eyes beatmap pack, which requires no difficulty reduction mods.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1606,&quot;achieved_percent&quot;:5.630243536780162e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-camellia-2.png&quot;,&quot;id&quot;:247,&quot;name&quot;:&quot;Camellia II&quot;,&quot;grouping&quot;:&quot;Beatmap Challenge Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;all-packs-camellia-2&quot;,&quot;description&quot;:&quot;Exit the atmosphere.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Camellia Challenges pack, which requires no difficulty reduction mods active.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1628,&quot;achieved_percent&quot;:5.707370160571671e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-usao.png&quot;,&quot;id&quot;:308,&quot;name&quot;:&quot;USAO Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Challenge Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;all-packs-usao&quot;,&quot;description&quot;:&quot;Now THAT is a showdown.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the USAO beatmap pack, which requires no difficulty reduction mods.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:35035,&quot;achieved_percent&quot;:0.0012282414838797819,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-gamer-1.png&quot;,&quot;id&quot;:7,&quot;name&quot;:&quot;Video Game Pack vol.1&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-gamer-1&quot;,&quot;description&quot;:&quot;A whole pack of video game goodness, done and dusted. Go you!&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:19853,&quot;achieved_percent&quot;:0.0006959976646058316,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-rhythm-1.png&quot;,&quot;id&quot;:8,&quot;name&quot;:&quot;Rhythm Game Pack vol.1&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-rhythm-1&quot;,&quot;description&quot;:&quot;Many beats were clicked, but the rhythm isn't over yet.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:20703,&quot;achieved_percent&quot;:0.0007257965874343692,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-internet-1.png&quot;,&quot;id&quot;:9,&quot;name&quot;:&quot;Internet! Pack vol.1&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-internet-1&quot;,&quot;description&quot;:&quot;Did somebody say something about IRC and ICQ?&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:43327,&quot;achieved_percent&quot;:0.0015189387404612334,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-anime-1.png&quot;,&quot;id&quot;:10,&quot;name&quot;:&quot;Anime Pack vol.1&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-anime-1&quot;,&quot;description&quot;:&quot;I-it's not like I'm proud of you or anything..&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:8206,&quot;achieved_percent&quot;:0.00028768230674232884,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-motoloid.png&quot;,&quot;id&quot;:179,&quot;name&quot;:&quot;MOtOLOiD&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-motoloid&quot;,&quot;description&quot;:&quot;Legends made manifest, by the mappers of the Guild.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the MOtOLOiD Mapper's Guild pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:9410,&quot;achieved_percent&quot;:0.0003298916044900456,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-mappersguild-01.png&quot;,&quot;id&quot;:185,&quot;name&quot;:&quot;Mappers' Guild Pack I&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-mappersguild-01&quot;,&quot;description&quot;:&quot;The first among many to come.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete all of the beatmaps in the Mappers' Guild I pack..&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:21858,&quot;achieved_percent&quot;:0.0007662880649249114,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-gamer-2.png&quot;,&quot;id&quot;:11,&quot;name&quot;:&quot;Video Game Pack vol.2&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-gamer-2&quot;,&quot;description&quot;:&quot;The sequel was no match for your skills, obviously.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:30165,&quot;achieved_percent&quot;:0.001057511184850396,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-anime-2.png&quot;,&quot;id&quot;:12,&quot;name&quot;:&quot;Anime Pack vol.2&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-anime-2&quot;,&quot;description&quot;:&quot;Truly dedicated to 2D.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:14962,&quot;achieved_percent&quot;:0.0005245311568947994,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-internet-2.png&quot;,&quot;id&quot;:18,&quot;name&quot;:&quot;Internet! Pack vol.2&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-internet-2&quot;,&quot;description&quot;:&quot;Straight from an albino black sheep. Wait, what?&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:13089,&quot;achieved_percent&quot;:0.00045886835400321007,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-rhythm-2.png&quot;,&quot;id&quot;:19,&quot;name&quot;:&quot;Rhythm Game Pack vol.2&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-rhythm-2&quot;,&quot;description&quot;:&quot;You just can't stop the beat.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:4561,&quot;achieved_percent&quot;:0.00015989751414230584,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-cranky.png&quot;,&quot;id&quot;:189,&quot;name&quot;:&quot;Cranky&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-cranky&quot;,&quot;description&quot;:&quot;The grandfather of rhythm gaming music, brought to life by the mappers of the Guild and guests alike.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Cranky pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:7027,&quot;achieved_percent&quot;:0.00024634944790133373,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-mappersguild-02.png&quot;,&quot;id&quot;:190,&quot;name&quot;:&quot;Mappers' Guild Pack II&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-mappersguild-02&quot;,&quot;description&quot;:&quot;A variable dream of the future.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete all of the beatmaps in the Mappers' Guild II pack..&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:18392,&quot;achieved_percent&quot;:0.0006447785748970158,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-gamer-3.png&quot;,&quot;id&quot;:14,&quot;name&quot;:&quot;Video Game Pack vol.3&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-gamer-3&quot;,&quot;description&quot;:&quot;True dedication to the gaming art.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:26506,&quot;achieved_percent&quot;:0.0009292355864626088,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-anime-3.png&quot;,&quot;id&quot;:25,&quot;name&quot;:&quot;Anime Pack vol.3&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-anime-3&quot;,&quot;description&quot;:&quot;You did it for the waifus.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:11730,&quot;achieved_percent&quot;:0.0004112251350338188,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-rhythm-3.png&quot;,&quot;id&quot;:26,&quot;name&quot;:&quot;Rhythm Game Pack vol.3&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-rhythm-3&quot;,&quot;description&quot;:&quot;Everyone knows the classics play better on osu! anyway.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:13271,&quot;achieved_percent&quot;:0.00046524882924414403,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-internet-3.png&quot;,&quot;id&quot;:27,&quot;name&quot;:&quot;Internet! Pack vol.3&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-internet-3&quot;,&quot;description&quot;:&quot;You didn't stumble upon this one, I'm guessing.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:5184,&quot;achieved_percent&quot;:0.00018173837169781044,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-hyun.png&quot;,&quot;id&quot;:208,&quot;name&quot;:&quot;HyuN&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-hyun&quot;,&quot;description&quot;:&quot;Digital punk goes into overdrive!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the HyuN pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4073,&quot;achieved_percent&quot;:0.00014278942668309838,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-mappersguild-03.png&quot;,&quot;id&quot;:226,&quot;name&quot;:&quot;Mappers' Guild Pack III&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-mappersguild-03&quot;,&quot;description&quot;:&quot;Sunrise was the end of a very magical night for one very special girl.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete all maps in the Mappers' Guild Pack III.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:24244,&quot;achieved_percent&quot;:0.0008499353941824299,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-anime-4.png&quot;,&quot;id&quot;:34,&quot;name&quot;:&quot;Anime Pack vol.4&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-anime-4&quot;,&quot;description&quot;:&quot;Has your ship not sailed?&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:9777,&quot;achieved_percent&quot;:0.00034275772764072004,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-rhythm-4.png&quot;,&quot;id&quot;:35,&quot;name&quot;:&quot;Rhythm Game Pack vol.4&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-rhythm-4&quot;,&quot;description&quot;:&quot;A click away? More like, right here.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:11667,&quot;achieved_percent&quot;:0.0004090165089888801,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-internet-4.png&quot;,&quot;id&quot;:36,&quot;name&quot;:&quot;Internet! Pack vol.4&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-internet-4&quot;,&quot;description&quot;:&quot;Must... have... more... memes...&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:15703,&quot;achieved_percent&quot;:0.0005505088060900303,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-gamer-4.png&quot;,&quot;id&quot;:37,&quot;name&quot;:&quot;Video Game Pack vol.4&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-gamer-4&quot;,&quot;description&quot;:&quot;You are Player 1.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:6341,&quot;achieved_percent&quot;:0.00022229996430089046,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-highteamusic.png&quot;,&quot;id&quot;:191,&quot;name&quot;:&quot;High Tea Music&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-highteamusic&quot;,&quot;description&quot;:&quot;Silently journeying to invade the skies.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete all of the beatmaps in the Mappers' Guild III\/High Tea Music pack..&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4135,&quot;achieved_percent&quot;:0.00014496299517176818,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-mappersguild-04.png&quot;,&quot;id&quot;:227,&quot;name&quot;:&quot;Mappers' Guild Pack IV&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-mappersguild-04&quot;,&quot;description&quot;:&quot;This freeway is a sensation and boy, does it love you!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete all maps in the Mappers' Guild Pack IV.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4103,&quot;achieved_percent&quot;:0.00014384115337116442,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-culprate.png&quot;,&quot;id&quot;:206,&quot;name&quot;:&quot;Culprate&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-culprate&quot;,&quot;description&quot;:&quot;A dream of whispers, light, and things to come.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete all of the beatmaps in the Mappers' Guild IV\/Culprate pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3793,&quot;achieved_percent&quot;:0.0001329733109278154,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-tieff.png&quot;,&quot;id&quot;:214,&quot;name&quot;:&quot;tieff&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-tieff&quot;,&quot;description&quot;:&quot;Flow.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the tieff pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3811,&quot;achieved_percent&quot;:0.00013360434694065503,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-icdd.png&quot;,&quot;id&quot;:213,&quot;name&quot;:&quot;Imperial Circus Dead Decadence&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-icdd&quot;,&quot;description&quot;:&quot;A little kite once sang me a song...&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Imperial Circus Dead Decadence pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3189,&quot;achieved_percent&quot;:0.00011179854694141928,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-mappersguild-05.png&quot;,&quot;id&quot;:263,&quot;name&quot;:&quot;Mappers' Guild Pack V&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-mappersguild-05&quot;,&quot;description&quot;:&quot;Invisible birdwatching.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Mappers' Guild V pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3206,&quot;achieved_percent&quot;:0.00011239452539799003,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-afterparty.png&quot;,&quot;id&quot;:229,&quot;name&quot;:&quot;Afterparty&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-afterparty&quot;,&quot;description&quot;:&quot;Encore to the core.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete the Afterparty beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3136,&quot;achieved_percent&quot;:0.00010994049645916929,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-mappersguild-06.png&quot;,&quot;id&quot;:264,&quot;name&quot;:&quot;Mappers' Guild Pack VI&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-mappersguild-06&quot;,&quot;description&quot;:&quot;Turn your superpower to hyperdrive!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Mappers' Guild VI pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2944,&quot;achieved_percent&quot;:0.00010320944565554668,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-benbriggs.png&quot;,&quot;id&quot;:230,&quot;name&quot;:&quot;Ben Briggs&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-benbriggs&quot;,&quot;description&quot;:&quot;Chiptunes, Pokemon, oh my!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Ben Briggs pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2750,&quot;achieved_percent&quot;:9.640827973938633e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-carpooltunnel.png&quot;,&quot;id&quot;:231,&quot;name&quot;:&quot;Carpool Tunnel&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-carpooltunnel&quot;,&quot;description&quot;:&quot;Not to be confused with an injury common to top-end players and people who watch anime.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Carpool Tunnel pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3187,&quot;achieved_percent&quot;:0.00011172843182888154,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-creo.png&quot;,&quot;id&quot;:232,&quot;name&quot;:&quot;Creo&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-creo&quot;,&quot;description&quot;:&quot;Dashing geometrically to a beatmap near you.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Creo pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4361,&quot;achieved_percent&quot;:0.0001528860028885323,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-cysmix.png&quot;,&quot;id&quot;:233,&quot;name&quot;:&quot;cYsmix&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-cysmix&quot;,&quot;description&quot;:&quot;Dead funky. For real.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the cYsmix pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4027,&quot;achieved_percent&quot;:0.00014117677909473045,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-fractaldreamers.png&quot;,&quot;id&quot;:234,&quot;name&quot;:&quot;Fractal Dreamers&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-fractaldreamers&quot;,&quot;description&quot;:&quot;Shattered dreams and muted skies never sounded so good.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Fractal Dreamers pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2405,&quot;achieved_percent&quot;:8.431342282662696e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-lukhash.png&quot;,&quot;id&quot;:235,&quot;name&quot;:&quot;LukHash&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-lukhash&quot;,&quot;description&quot;:&quot;There's a ghost in this here machine.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the LukHash pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3343,&quot;achieved_percent&quot;:0.00011719741060682492,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-namirin.png&quot;,&quot;id&quot;:236,&quot;name&quot;:&quot;*namirin&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-namirin&quot;,&quot;description&quot;:&quot;Five colors to make your world sing!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the *namirin pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2605,&quot;achieved_percent&quot;:9.13249340804005e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-onumi.png&quot;,&quot;id&quot;:237,&quot;name&quot;:&quot;onumi&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-onumi&quot;,&quot;description&quot;:&quot;There's a lot going on here.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the onumi pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2387,&quot;achieved_percent&quot;:8.368238681378734e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-theflashbulb.png&quot;,&quot;id&quot;:238,&quot;name&quot;:&quot;The Flashbulb&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-theflashbulb&quot;,&quot;description&quot;:&quot;Not merely incandescent.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of The Flashbulb pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4404,&quot;achieved_percent&quot;:0.0001543934778080936,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-undeadcorporation.png&quot;,&quot;id&quot;:239,&quot;name&quot;:&quot;Undead Corporation&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-undeadcorporation&quot;,&quot;description&quot;:&quot;Diversifying underground assets. Literally.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Undead Corporation pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3003,&quot;achieved_percent&quot;:0.00010527784147540988,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-wispx.png&quot;,&quot;id&quot;:240,&quot;name&quot;:&quot;Wisp X&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-wispx&quot;,&quot;description&quot;:&quot;Sunset and the moon.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Wisp X pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:5226,&quot;achieved_percent&quot;:0.0001832107890611029,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-camellia-1.png&quot;,&quot;id&quot;:246,&quot;name&quot;:&quot;Camellia I&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-camellia-1&quot;,&quot;description&quot;:&quot;This is the entrance to the jungle.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Camellia Sets pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2444,&quot;achieved_percent&quot;:8.56806675211128e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-celldweller.png&quot;,&quot;id&quot;:248,&quot;name&quot;:&quot;Celldweller&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-celldweller&quot;,&quot;description&quot;:&quot;The end of an empire is no obstacle to you.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Celldweller pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2637,&quot;achieved_percent&quot;:9.244677588100428e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-cranky2.png&quot;,&quot;id&quot;:249,&quot;name&quot;:&quot;Cranky II&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-cranky2&quot;,&quot;description&quot;:&quot;Even crankier than before!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Cranky 2 pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4770,&quot;achieved_percent&quot;:0.0001672245434024992,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-CuteAnimeGirls.png&quot;,&quot;id&quot;:250,&quot;name&quot;:&quot;Cute Anime Girls&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-CuteAnimeGirls&quot;,&quot;description&quot;:&quot;Not to be confused with cute flamb\u00e9 grills.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Cute Anime Girls pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2282,&quot;achieved_percent&quot;:8.000134340555622e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-ELFENSJoN.png&quot;,&quot;id&quot;:251,&quot;name&quot;:&quot;ELFENSJoN&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-ELFENSJoN&quot;,&quot;description&quot;:&quot;A world all of your own.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the ELFENSJoN pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3660,&quot;achieved_percent&quot;:0.00012831065594405599,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-HyperPotions.png&quot;,&quot;id&quot;:252,&quot;name&quot;:&quot;Hyper Potions&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-HyperPotions&quot;,&quot;description&quot;:&quot;Gain 200 HP.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Hyper Potions pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3610,&quot;achieved_percent&quot;:0.0001265577781306126,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-KolaKid.png&quot;,&quot;id&quot;:253,&quot;name&quot;:&quot;Kola Kid&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-KolaKid&quot;,&quot;description&quot;:&quot;Remember, the Earth is counting on you.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Kola Kid pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3767,&quot;achieved_percent&quot;:0.00013206181446482484,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-leaf.png&quot;,&quot;id&quot;:254,&quot;name&quot;:&quot;LeaF&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-leaf&quot;,&quot;description&quot;:&quot;Calamity was not in your fortune.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the LeaF pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:5773,&quot;achieved_percent&quot;:0.00020238727234017358,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-PandaEyes.png&quot;,&quot;id&quot;:255,&quot;name&quot;:&quot;Panda Eyes&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-PandaEyes&quot;,&quot;description&quot;:&quot;Embrace the immortal flame.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Panda Eyes pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3213,&quot;achieved_percent&quot;:0.0001126399282918721,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-PUP.png&quot;,&quot;id&quot;:256,&quot;name&quot;:&quot;PUP&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-PUP&quot;,&quot;description&quot;:&quot;Finally, some closure.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the PUP pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3244,&quot;achieved_percent&quot;:0.000113726712536207,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-RickyMontgomery.png&quot;,&quot;id&quot;:257,&quot;name&quot;:&quot;Ricky Montgomery&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-RickyMontgomery&quot;,&quot;description&quot;:&quot;All hook and sinker.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Ricky Montgomery pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2112,&quot;achieved_percent&quot;:7.404155883984871e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-Rin.png&quot;,&quot;id&quot;:258,&quot;name&quot;:&quot;Rin&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-Rin&quot;,&quot;description&quot;:&quot;Two minds, and a house full of ghosts.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Rin\/Function Phantom pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:9553,&quot;achieved_percent&quot;:0.0003349048350364937,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-S3RL.png&quot;,&quot;id&quot;:259,&quot;name&quot;:&quot;S3RL&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-S3RL&quot;,&quot;description&quot;:&quot;You'll never get any of these out of your head.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the S3RL pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3055,&quot;achieved_percent&quot;:0.000107100834401391,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-SoundSouler.png&quot;,&quot;id&quot;:260,&quot;name&quot;:&quot;Sound Souler&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-SoundSouler&quot;,&quot;description&quot;:&quot;Return color to your life.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Sound Souler pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3683,&quot;achieved_percent&quot;:0.00012911697973823995,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-Teminite.png&quot;,&quot;id&quot;:261,&quot;name&quot;:&quot;Teminite&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-Teminite&quot;,&quot;description&quot;:&quot;It's all about the state of mind.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Teminite pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4302,&quot;achieved_percent&quot;:0.0001508176070686691,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-VINXIS.png&quot;,&quot;id&quot;:262,&quot;name&quot;:&quot;VINXIS&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-VINXIS&quot;,&quot;description&quot;:&quot;Staying on track.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the VINXIS pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4099,&quot;achieved_percent&quot;:0.00014370092314608895,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-touhou.png&quot;,&quot;id&quot;:282,&quot;name&quot;:&quot;Touhou Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-touhou&quot;,&quot;description&quot;:&quot;The bamboo isn't the only thing dancing!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Touhou beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3327,&quot;achieved_percent&quot;:0.00011663648970652303,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-ginkiha.png&quot;,&quot;id&quot;:283,&quot;name&quot;:&quot;ginkiha Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-ginkiha&quot;,&quot;description&quot;:&quot;The night stars shine the brightest of all.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the ginkiha beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4184,&quot;achieved_percent&quot;:0.0001466808154289427,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-vocaloid.png&quot;,&quot;id&quot;:288,&quot;name&quot;:&quot;Vocaloid Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-vocaloid&quot;,&quot;description&quot;:&quot;What's life without a song?&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Vocaloid beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2748,&quot;achieved_percent&quot;:9.63381646268486e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-maduk.png&quot;,&quot;id&quot;:289,&quot;name&quot;:&quot;Maduk Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-maduk&quot;,&quot;description&quot;:&quot;You took control.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Maduk beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3155,&quot;achieved_percent&quot;:0.00011060659002827777,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-aitsuki.png&quot;,&quot;id&quot;:290,&quot;name&quot;:&quot;Aitsuki Nakuru Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-aitsuki&quot;,&quot;description&quot;:&quot;Took part in the Joker's Parade.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Aitsuki Nakuru beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3218,&quot;achieved_percent&quot;:0.00011281521607321644,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-omoi.png&quot;,&quot;id&quot;:295,&quot;name&quot;:&quot;Omoi Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-omoi&quot;,&quot;description&quot;:&quot;A whole new meaning to chill.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Omoi beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3066,&quot;achieved_percent&quot;:0.00010748646752034855,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-chill.png&quot;,&quot;id&quot;:296,&quot;name&quot;:&quot;Chill Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-chill&quot;,&quot;description&quot;:&quot;Just vibin'.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Chill beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2323,&quot;achieved_percent&quot;:8.14387032125798e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-rohi.png&quot;,&quot;id&quot;:309,&quot;name&quot;:&quot;Rohi Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-rohi&quot;,&quot;description&quot;:&quot;An artifact of true skill.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Rohi beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2226,&quot;achieved_percent&quot;:7.803812025449962e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-packs-drum_and_bass.png&quot;,&quot;id&quot;:310,&quot;name&quot;:&quot;Drum &amp; Bass Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;all-packs-drum_and_bass&quot;,&quot;description&quot;:&quot;727? More like 174, baby!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Drum &amp; Bass beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2041,&quot;achieved_percent&quot;:0.000164577409803153,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/catch-packs-ghostlove.png&quot;,&quot;id&quot;:335,&quot;name&quot;:&quot;in love with a ghost&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;catch-packs-ghostlove&quot;,&quot;description&quot;:&quot;A quasi-Valentine's story about coffee, cuteness, lonely mornings and laughs.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the in love with a ghost beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:377,&quot;achieved_percent&quot;:2.683385367520944e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-packs-chroma.png&quot;,&quot;id&quot;:360,&quot;name&quot;:&quot;Chroma Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;taiko-packs-chroma&quot;,&quot;description&quot;:&quot;@_@&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Chroma beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:410,&quot;achieved_percent&quot;:3.306062617309786e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/catch-packs-mili.png&quot;,&quot;id&quot;:361,&quot;name&quot;:&quot;Mili Pack&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;catch-packs-mili&quot;,&quot;description&quot;:&quot;With so much sacrifice, I don't even bother to survive.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the Mili beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:482,&quot;achieved_percent&quot;:3.3476743907423606e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-packs-4k-globe.png&quot;,&quot;id&quot;:362,&quot;name&quot;:&quot;4K Globetrotter&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;mania-packs-4k-globe&quot;,&quot;description&quot;:&quot;Around the world, a-round the world.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the 4K beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:639,&quot;achieved_percent&quot;:4.4380994516273206e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-packs-7k-world-cup.png&quot;,&quot;id&quot;:363,&quot;name&quot;:&quot;7K World Cup Anthology&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;mania-packs-7k-world-cup&quot;,&quot;description&quot;:&quot;A spread worthy of a world stage.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the 7K beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2489,&quot;achieved_percent&quot;:8.725825755321185e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/loved-seasonal-2021-winter.png&quot;,&quot;id&quot;:311,&quot;name&quot;:&quot;Project Loved: Winter 2021&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;loved-seasonal-2021-winter&quot;,&quot;description&quot;:&quot;You're very welcome for the music.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play any of the Project Loved: Winter 2021 beatmap packs.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2028,&quot;achieved_percent&quot;:7.109672411326381e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/loved-seasonal-2022-spring.png&quot;,&quot;id&quot;:312,&quot;name&quot;:&quot;Project Loved: Spring 2022&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;loved-seasonal-2022-spring&quot;,&quot;description&quot;:&quot;You promised that foolish heroes would be good for me...&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play any of the Project Loved: Spring 2022 beatmap packs.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1842,&quot;achieved_percent&quot;:6.457601864725441e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/loved-seasonal-2022-summer.png&quot;,&quot;id&quot;:313,&quot;name&quot;:&quot;Project Loved: Summer 2022&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;loved-seasonal-2022-summer&quot;,&quot;description&quot;:&quot;Alright, fine. You don't sound like dragonforce.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play any of the Project Loved: Summer 2022 beatmap packs.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1710,&quot;achieved_percent&quot;:5.9948421219763865e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/loved-seasonal-2022-autumn.png&quot;,&quot;id&quot;:314,&quot;name&quot;:&quot;Project Loved: Autumn 2022&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;loved-seasonal-2022-autumn&quot;,&quot;description&quot;:&quot;There's a god-ish bee in my damned salad.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play any of the Project Loved: Autumn 2022 beatmap packs.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1724,&quot;achieved_percent&quot;:6.043922700752801e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/loved-seasonal-2022-winter.png&quot;,&quot;id&quot;:315,&quot;name&quot;:&quot;Project Loved: Winter 2022&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;loved-seasonal-2022-winter&quot;,&quot;description&quot;:&quot;Chasing nightmares in square, alien and propane forms.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play any of the Project Loved: Winter 2022 beatmap packs.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1767,&quot;achieved_percent&quot;:6.194670192708932e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/loved-seasonal-2023-spring.png&quot;,&quot;id&quot;:316,&quot;name&quot;:&quot;Project Loved: Spring 2023&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;loved-seasonal-2023-spring&quot;,&quot;description&quot;:&quot;Phase one: turn all humans and their fickle souls into orange cordial.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play any of the Project Loved: Spring 2023 beatmap pack.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1582,&quot;achieved_percent&quot;:5.546105401734879e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/loved-seasonal-2023-summer.png&quot;,&quot;id&quot;:325,&quot;name&quot;:&quot;Project Loved: Summer 2023&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;loved-seasonal-2023-summer&quot;,&quot;description&quot;:&quot;Keep those psychopathic bugs away from my flowers!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play any of the Project Loved: Summer 2023 beatmap packs.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1220,&quot;achieved_percent&quot;:4.277021864801866e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/loved-seasonal-2024.png&quot;,&quot;id&quot;:350,&quot;name&quot;:&quot;Project Loved: Best of 2024&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;loved-seasonal-2024&quot;,&quot;description&quot;:&quot;In the freezing midwinter, I can still barely hear your voice...&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play any of the Project Loved: Best of 2024 beatmap packs.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:485,&quot;achieved_percent&quot;:1.700291479040086e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/loved-seasonal-2025.png&quot;,&quot;id&quot;:359,&quot;name&quot;:&quot;Project Loved: Best of 2025&quot;,&quot;grouping&quot;:&quot;Beatmap Packs&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;loved-seasonal-2025&quot;,&quot;description&quot;:&quot;Isn't it about time for a good morning?&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play any of the Project Loved: Best of 2025 beatmap packs.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:5515,&quot;achieved_percent&quot;:0.00019334242282280568,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2017-01.png&quot;,&quot;id&quot;:162,&quot;name&quot;:&quot;January\/February 2017 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2017-01&quot;,&quot;description&quot;:&quot;Two for the price of one.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the January\/February Spotlights for 2017.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4862,&quot;achieved_percent&quot;:0.00017044983857923503,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2017-03.png&quot;,&quot;id&quot;:163,&quot;name&quot;:&quot;March 2017 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2017-03&quot;,&quot;description&quot;:&quot;March ever onwards.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the March Spotlights for 2017.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:18415,&quot;achieved_percent&quot;:0.0006455848986911997,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2017-04.png&quot;,&quot;id&quot;:164,&quot;name&quot;:&quot;April 2017 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2017-04&quot;,&quot;description&quot;:&quot;Pitch.. WHAT?&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the April Spotlights for 2017.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:5970,&quot;achieved_percent&quot;:0.00020929361092514052,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2017-05.png&quot;,&quot;id&quot;:165,&quot;name&quot;:&quot;May 2017 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2017-05&quot;,&quot;description&quot;:&quot;May your accuracy forever be swift and true.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the May Spotlights for 2017.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:40289,&quot;achieved_percent&quot;:0.001412433884516413,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2017-06.png&quot;,&quot;id&quot;:166,&quot;name&quot;:&quot;June 2017 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2017-06&quot;,&quot;description&quot;:&quot;Innocence destroyed.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the June Spotlights for 2017.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4776,&quot;achieved_percent&quot;:0.0001674348887401124,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2017-07.png&quot;,&quot;id&quot;:167,&quot;name&quot;:&quot;July 2017 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2017-07&quot;,&quot;description&quot;:&quot;Where it all begins.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the July Spotlights for 2017.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3935,&quot;achieved_percent&quot;:0.00013795148391799463,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2017-08.png&quot;,&quot;id&quot;:169,&quot;name&quot;:&quot;August 2017 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2017-08&quot;,&quot;description&quot;:&quot;Ah, yes. Something just like this.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the August Spotlights for 2017.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:11017,&quot;achieved_percent&quot;:0.0003862290974141161,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2017-09.png&quot;,&quot;id&quot;:180,&quot;name&quot;:&quot;September 2017 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2017-09&quot;,&quot;description&quot;:&quot;New beginnings, time travelers, and airborne robots. Oh my!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the September Spotlights for 2017.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:5571,&quot;achieved_percent&quot;:0.00019530564597386227,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2017-10.png&quot;,&quot;id&quot;:181,&quot;name&quot;:&quot;October 2017 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2017-10&quot;,&quot;description&quot;:&quot;First, one must distract a punk rock girl. Then, they must put on the radio.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the October Spotlights for 2017.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:8650,&quot;achieved_percent&quot;:0.0003032478617257061,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2017-11.png&quot;,&quot;id&quot;:182,&quot;name&quot;:&quot;November 2017 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2017-11&quot;,&quot;description&quot;:&quot;The end of an era, and the start of something new!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the November Spotlights for 2017.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:5118,&quot;achieved_percent&quot;:0.0001794245729840652,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2017-12.png&quot;,&quot;id&quot;:183,&quot;name&quot;:&quot;December 2017 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2017-12&quot;,&quot;description&quot;:&quot;Impulse to end the year!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the December Spotlights for 2017.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:9072,&quot;achieved_percent&quot;:0.0003180421504711683,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2018-01.png&quot;,&quot;id&quot;:184,&quot;name&quot;:&quot;January 2018 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2018-01&quot;,&quot;description&quot;:&quot;Reality distorts.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the January Spotlights for 2018.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4475,&quot;achieved_percent&quot;:0.0001568825643031832,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2018-02.png&quot;,&quot;id&quot;:186,&quot;name&quot;:&quot;February 2018 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2018-02&quot;,&quot;description&quot;:&quot;Let's jump for dreams of future candy!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the February Spotlights for 2018.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3422,&quot;achieved_percent&quot;:0.00011996695755206547,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2018-03.png&quot;,&quot;id&quot;:187,&quot;name&quot;:&quot;March 2018 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2018-03&quot;,&quot;description&quot;:&quot;Transport me to Nirvana on the backs of angels!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the March Spotlights for 2018.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3923,&quot;achieved_percent&quot;:0.0001375307932427682,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2018-04.png&quot;,&quot;id&quot;:188,&quot;name&quot;:&quot;April 2018 Spotlight&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;spotlight-2018-04&quot;,&quot;description&quot;:&quot;A lesson from a DJ: drop kick captivatingly.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Complete any gamemode version of the April Spotlights for 2018.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3931,&quot;achieved_percent&quot;:0.00013781125369291916,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2018-summer.png&quot;,&quot;id&quot;:205,&quot;name&quot;:&quot;Summer 2018 Beatmap Spotlights&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:8,&quot;slug&quot;:&quot;spotlight-2018-summer&quot;,&quot;description&quot;:&quot;The hottest beatmaps from Summer 2018!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the maps from one mode of the Summer 2018 Beatmap Spotlights.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3434,&quot;achieved_percent&quot;:0.00012038764822729188,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2019-winter.png&quot;,&quot;id&quot;:209,&quot;name&quot;:&quot;Winter 2019 Beatmap Spotlights&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:8,&quot;slug&quot;:&quot;spotlight-2019-winter&quot;,&quot;description&quot;:&quot;The chillest beatmaps from Winter 2019!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the maps from one mode of the Winter 2019 Beatmap Spotlights.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3997,&quot;achieved_percent&quot;:0.00014012505240666443,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2020-winter.png&quot;,&quot;id&quot;:241,&quot;name&quot;:&quot;Winter 2020 Beatmap Spotlights&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:8,&quot;slug&quot;:&quot;spotlight-2020-winter&quot;,&quot;description&quot;:&quot;The best of Winter 2020 in beatmap form!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the maps from one mode of the Winter 2020 Beatmap Spotlights.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3138,&quot;achieved_percent&quot;:0.00011001061157170703,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2018-autumn.png&quot;,&quot;id&quot;:207,&quot;name&quot;:&quot;Fall 2018 Beatmap Spotlights&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:8,&quot;slug&quot;:&quot;spotlight-2018-autumn&quot;,&quot;description&quot;:&quot;The most fabulous beatmaps from Fall 2018!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the maps from one mode of the Fall 2018 Beatmap Spotlights.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3510,&quot;achieved_percent&quot;:0.00012305202250372584,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2019-spring.png&quot;,&quot;id&quot;:210,&quot;name&quot;:&quot;Spring 2019 Beatmap Spotlights&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:8,&quot;slug&quot;:&quot;spotlight-2019-spring&quot;,&quot;description&quot;:&quot;A bloomin' good time from Spring 2019!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the maps from one mode of the Spring 2019 Beatmap Spotlights.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3237,&quot;achieved_percent&quot;:0.00011348130964232493,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2019-summer.png&quot;,&quot;id&quot;:215,&quot;name&quot;:&quot;Summer 2019 Beatmap Spotlights&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:8,&quot;slug&quot;:&quot;spotlight-2019-summer&quot;,&quot;description&quot;:&quot;Blaze a trail through the best of Summer 2019!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the maps from one mode of the Summer 2019 Beatmap Spotlights.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2923,&quot;achieved_percent&quot;:0.00010247323697390046,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/spotlight-2019-autumn.png&quot;,&quot;id&quot;:228,&quot;name&quot;:&quot;Autumn 2019 Beatmap Spotlights&quot;,&quot;grouping&quot;:&quot;Beatmap Spotlights&quot;,&quot;ordering&quot;:8,&quot;slug&quot;:&quot;spotlight-2019-autumn&quot;,&quot;description&quot;:&quot;Fall straight into the best maps of Autumn 2019!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Play all of the maps from one mode of the Autumn 2019 Beatmap Spotlights.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:97349,&quot;achieved_percent&quot;:0.0034128180452180075,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-bunny.png&quot;,&quot;id&quot;:6,&quot;name&quot;:&quot;Don't let the bunny distract you!&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-bunny&quot;,&quot;description&quot;:&quot;The order was indeed, not a rabbit.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:2761785,&quot;achieved_percent&quot;:0.09682143304001493,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-rank-s.png&quot;,&quot;id&quot;:15,&quot;name&quot;:&quot;S-Ranker&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-rank-s&quot;,&quot;description&quot;:&quot;Accuracy is really underrated.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:406308,&quot;achieved_percent&quot;:0.01424416557249112,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-improved.png&quot;,&quot;id&quot;:16,&quot;name&quot;:&quot;Most Improved&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-improved&quot;,&quot;description&quot;:&quot;Now THAT is improvement.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:47557,&quot;achieved_percent&quot;:0.001667232203478544,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-dancer.png&quot;,&quot;id&quot;:17,&quot;name&quot;:&quot;Non-stop Dancer&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-dancer&quot;,&quot;description&quot;:&quot;Can you still feel your feet after that?&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1400207,&quot;achieved_percent&quot;:0.04908783569056251,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-consolation_prize.png&quot;,&quot;id&quot;:38,&quot;name&quot;:&quot;Consolation Prize&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-consolation_prize&quot;,&quot;description&quot;:&quot;Well, it could be worse.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1752119,&quot;achieved_percent&quot;:0.061425010432252306,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-challenge_accepted.png&quot;,&quot;id&quot;:39,&quot;name&quot;:&quot;Challenge Accepted&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-challenge_accepted&quot;,&quot;description&quot;:&quot;Oh, you're ON.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1470949,&quot;achieved_percent&quot;:0.05156787733613476,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-stumbler.png&quot;,&quot;id&quot;:40,&quot;name&quot;:&quot;Stumbler&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-stumbler&quot;,&quot;description&quot;:&quot;No regrets.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:55119,&quot;achieved_percent&quot;:0.0019323374439837219,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-jackpot.png&quot;,&quot;id&quot;:41,&quot;name&quot;:&quot;Jackpot&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-jackpot&quot;,&quot;description&quot;:&quot;Lucky sevens is a mild understatement.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:204002,&quot;achieved_percent&quot;:0.007151811593961561,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-quick_draw.png&quot;,&quot;id&quot;:42,&quot;name&quot;:&quot;Quick Draw&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-quick_draw&quot;,&quot;description&quot;:&quot;It's high noon.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:541242,&quot;achieved_percent&quot;:0.018974621870074523,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-obsessed.png&quot;,&quot;id&quot;:43,&quot;name&quot;:&quot;Obsessed&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-obsessed&quot;,&quot;description&quot;:&quot;COMPLETION AT ALL COSTS.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:25112,&quot;achieved_percent&quot;:0.0008803653530238072,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-nonstop.png&quot;,&quot;id&quot;:44,&quot;name&quot;:&quot;Nonstop&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-nonstop&quot;,&quot;description&quot;:&quot;Breaks? What are those?&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:955,&quot;achieved_percent&quot;:3.3479966236768706e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-jack.png&quot;,&quot;id&quot;:45,&quot;name&quot;:&quot;Jack of All Trades&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-jack&quot;,&quot;description&quot;:&quot;Good at everything.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:5501531,&quot;achieved_percent&quot;:0.382102374244299,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-secret-meganekko.png&quot;,&quot;id&quot;:54,&quot;name&quot;:&quot;Twin Perspectives&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;mania-secret-meganekko&quot;,&quot;description&quot;:&quot;You met Mani and Mari, our twin osu!mania mascots.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:44561,&quot;achieved_percent&quot;:0.0015621997648970162,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-tidi.png&quot;,&quot;id&quot;:134,&quot;name&quot;:&quot;Time Dilation&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-tidi&quot;,&quot;description&quot;:&quot;Longer is shorter when all is said and done.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Time often flies when one is having fun, though rarely does it last forever.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:62020,&quot;achieved_percent&quot;:0.002174269639795178,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-afterimage.png&quot;,&quot;id&quot;:136,&quot;name&quot;:&quot;Afterimage&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;osu-secret-afterimage&quot;,&quot;description&quot;:&quot;But a glimpse of its true self.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Always coming behind the original image.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:790682,&quot;achieved_percent&quot;:0.027719378705780895,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-tothecore.png&quot;,&quot;id&quot;:137,&quot;name&quot;:&quot;To The Core&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-tothecore&quot;,&quot;description&quot;:&quot;In for a penny, in for a pound. Pounding bass, that is.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Double negatives sometimes &lt;strong&gt;do&lt;\/strong&gt; make a positive.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:607537,&quot;achieved_percent&quot;:0.02129876256291911,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-prepared.png&quot;,&quot;id&quot;:138,&quot;name&quot;:&quot;Prepared&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-prepared&quot;,&quot;description&quot;:&quot;Do it for real next time.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Preparation is key for all successful endeavours.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:129308,&quot;achieved_percent&quot;:0.004533222486014752,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-eclipse.png&quot;,&quot;id&quot;:139,&quot;name&quot;:&quot;Eclipse&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;osu-secret-eclipse&quot;,&quot;description&quot;:&quot;Something new born from absence.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Can't see the sun for the clouds. Or the moon, in this case.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:95461,&quot;achieved_percent&quot;:0.003346629378982385,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-reckless.png&quot;,&quot;id&quot;:140,&quot;name&quot;:&quot;Reckless Abandon&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-reckless&quot;,&quot;description&quot;:&quot;Throw it all to the wind.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Do it just because you can, even if the stakes are high.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:348735,&quot;achieved_percent&quot;:0.012225796885423598,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-tunnelvision.png&quot;,&quot;id&quot;:141,&quot;name&quot;:&quot;Tunnel Vision&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;osu-secret-tunnelvision&quot;,&quot;description&quot;:&quot;But it was right there..&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Afraid of the dark?&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:26445,&quot;achieved_percent&quot;:0.0009270970755302078,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-deception.png&quot;,&quot;id&quot;:142,&quot;name&quot;:&quot;Behold No Deception&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;osu-secret-deception&quot;,&quot;description&quot;:&quot;That wasn't easy at all!&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Sometimes the hard way is in fact, easier.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:122597,&quot;achieved_percent&quot;:0.004297951225894381,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-lightsout.png&quot;,&quot;id&quot;:144,&quot;name&quot;:&quot;Lights Out&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-lightsout&quot;,&quot;description&quot;:&quot;The party's just getting started.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Set the mood.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:838,&quot;achieved_percent&quot;:2.937823215331118e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-aeon.png&quot;,&quot;id&quot;:199,&quot;name&quot;:&quot;Aeon&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-aeon&quot;,&quot;description&quot;:&quot;In the mire of thawing time, memory shall be your guide.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;When time runs slow and sight fails you, how will you succeed?&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:38863,&quot;achieved_percent&quot;:0.0013624418092770076,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-uguushy.png&quot;,&quot;id&quot;:147,&quot;name&quot;:&quot;Camera Shy&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-uguushy&quot;,&quot;description&quot;:&quot;Stop being cute.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Uguu.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:983967,&quot;achieved_percent&quot;:0.034495478469209,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-nuked.png&quot;,&quot;id&quot;:148,&quot;name&quot;:&quot;The Sum Of All Fears&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-nuked&quot;,&quot;description&quot;:&quot;Unfortunate.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;The end comes when you least expect it.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:6425,&quot;achieved_percent&quot;:0.00022524479902747536,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-deka.png&quot;,&quot;id&quot;:149,&quot;name&quot;:&quot;Dekasight&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;osu-secret-deka&quot;,&quot;description&quot;:&quot;So big, yet so hard to see.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Size isn't everything.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:49542,&quot;achieved_percent&quot;:0.0017368214526722464,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-hourbeforethedawn.png&quot;,&quot;id&quot;:150,&quot;name&quot;:&quot;Hour Before The Dawn&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-hourbeforethedawn&quot;,&quot;description&quot;:&quot;Eleven skies of everlasting sunrise.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;The night where we belong.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:17920,&quot;achieved_percent&quot;:0.0006282314083381102,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-slowandsteady.png&quot;,&quot;id&quot;:151,&quot;name&quot;:&quot;Slow And Steady&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-slowandsteady&quot;,&quot;description&quot;:&quot;Win the race, or start again.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Take your time.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:667620,&quot;achieved_percent&quot;:0.02340512571622149,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-ntts.png&quot;,&quot;id&quot;:152,&quot;name&quot;:&quot;No Time To Spare&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-ntts&quot;,&quot;description&quot;:&quot;Places to be, things to do.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Think fast, click fast, be fast.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:33556,&quot;achieved_percent&quot;:0.0011763913581581266,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-sognare.png&quot;,&quot;id&quot;:153,&quot;name&quot;:&quot;Sognare&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-sognare&quot;,&quot;description&quot;:&quot;A dream in stop-motion, soon forever gone.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;\&quot;I saw three spires all around, and a world in halted time..\&quot;&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:26210,&quot;achieved_percent&quot;:0.000918858549807024,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-realtor.png&quot;,&quot;id&quot;:154,&quot;name&quot;:&quot;Realtor Extraordinaire&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-realtor&quot;,&quot;description&quot;:&quot;An acre-wide stride.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;The wrong kind of house.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:7494,&quot;achieved_percent&quot;:0.000262721326678895,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-kaleidoscope.png&quot;,&quot;id&quot;:223,&quot;name&quot;:&quot;Kaleidoscope&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-kaleidoscope&quot;,&quot;description&quot;:&quot;So many pretty colours. Most of them red.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;See the tiny colours up through the tube up close and personal, and slow right down.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:11237,&quot;achieved_percent&quot;:0.000393941759793267,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-meticulous.png&quot;,&quot;id&quot;:157,&quot;name&quot;:&quot;Meticulous&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;osu-secret-meticulous&quot;,&quot;description&quot;:&quot;The circle goes here, and then here, and then here..&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;This is the way it's SUPPOSED to be.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:42768,&quot;achieved_percent&quot;:0.0014993415665069364,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-infinitesimal.png&quot;,&quot;id&quot;:158,&quot;name&quot;:&quot;Infinitesimal&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;osu-secret-infinitesimal&quot;,&quot;description&quot;:&quot;Big word for something so very, very small.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Tiny in scope, big in meaning.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:9199,&quot;achieved_percent&quot;:0.0003224944601173145,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-equilibrium.png&quot;,&quot;id&quot;:159,&quot;name&quot;:&quot;Equilibrium&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;osu-secret-equilibrium&quot;,&quot;description&quot;:&quot;Balance in all things.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Seek the middle ground.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:26866,&quot;achieved_percent&quot;:0.0009418563067194012,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-impeccable.png&quot;,&quot;id&quot;:160,&quot;name&quot;:&quot;Impeccable&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-impeccable&quot;,&quot;description&quot;:&quot;Speed matters not to the exemplary.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Simply superb.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:18131,&quot;achieved_percent&quot;:0.0006356285527108413,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-quickmaffs.png&quot;,&quot;id&quot;:202,&quot;name&quot;:&quot;Quick Maths&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-quickmaffs&quot;,&quot;description&quot;:&quot;Beats per minute over... this isn't quick at all!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Where x equals beats per minute, and a variable unknown...&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:12610,&quot;achieved_percent&quot;:0.0004420757845504224,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-valediction.png&quot;,&quot;id&quot;:225,&quot;name&quot;:&quot;Valediction&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-valediction&quot;,&quot;description&quot;:&quot;One last time.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Time stood still as we waved farewell.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:26898,&quot;achieved_percent&quot;:0.0009429781485200049,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-tentoone.png&quot;,&quot;id&quot;:268,&quot;name&quot;:&quot;Ten To One&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-tentoone&quot;,&quot;description&quot;:&quot;From one extreme to another.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;From a marathon to a sprint.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:23779,&quot;achieved_percent&quot;:0.0008336336305174064,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-exquisite.png&quot;,&quot;id&quot;:269,&quot;name&quot;:&quot;Exquisite&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-exquisite&quot;,&quot;description&quot;:&quot;Indubitably.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Do it once with true calibre, then do it again.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:20690,&quot;achieved_percent&quot;:0.000725340839202874,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-persistenceiskey.png&quot;,&quot;id&quot;:270,&quot;name&quot;:&quot;Persistence Is Key&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-persistenceiskey&quot;,&quot;description&quot;:&quot;Don't let your dreams be dreams.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Don't give up!&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3068,&quot;achieved_percent&quot;:0.00010755658263288628,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-madscientist.png&quot;,&quot;id&quot;:271,&quot;name&quot;:&quot;Mad Scientist&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-madscientist&quot;,&quot;description&quot;:&quot;The experiment... it's all gone!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Become invisible.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:272461,&quot;achieved_percent&quot;:0.009551816838571979,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-tribulation.png&quot;,&quot;id&quot;:272,&quot;name&quot;:&quot;Tribulation&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-tribulation&quot;,&quot;description&quot;:&quot;Success is inevitable... eventually.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Struggle and then stop.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:6636,&quot;achieved_percent&quot;:0.00023264194340020644,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-rightontime.png&quot;,&quot;id&quot;:273,&quot;name&quot;:&quot;Right On Time&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-rightontime&quot;,&quot;description&quot;:&quot;The first minute is always the hardest.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Every hour's got sixty, but your timer only wants one.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:5706,&quot;achieved_percent&quot;:0.00020003841607015943,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-replica.png&quot;,&quot;id&quot;:274,&quot;name&quot;:&quot;Replica&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-replica&quot;,&quot;description&quot;:&quot;One just like the other.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Duplicate.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:9945,&quot;achieved_percent&quot;:0.00034864739709388983,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-allgood.png&quot;,&quot;id&quot;:275,&quot;name&quot;:&quot;All Good&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-allgood&quot;,&quot;description&quot;:&quot;Better now, thanks!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;You got this.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1473,&quot;achieved_percent&quot;:5.163978038404221e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-inmemoriam.png&quot;,&quot;id&quot;:277,&quot;name&quot;:&quot;In Memoriam&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;osu-secret-inmemoriam&quot;,&quot;description&quot;:&quot;In loving memory of your sanity, long forgotten.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Conquer a test of the most frustrating combination of mods imaginable.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1080,&quot;achieved_percent&quot;:3.786216077037718e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-sanguine.png&quot;,&quot;id&quot;:278,&quot;name&quot;:&quot;Sanguine&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;osu-secret-sanguine&quot;,&quot;description&quot;:&quot;Timeless thorns still draw blood.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Return to the past, when everything was simpler.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:6500,&quot;achieved_percent&quot;:0.00022787411574764043,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-notagain.png&quot;,&quot;id&quot;:279,&quot;name&quot;:&quot;Not Again&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-notagain&quot;,&quot;description&quot;:&quot;Regret everything.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;You had it all, and then it was gone.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4134,&quot;achieved_percent&quot;:0.0001449279376154993,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-deliberation.png&quot;,&quot;id&quot;:285,&quot;name&quot;:&quot;Deliberation&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-deliberation&quot;,&quot;description&quot;:&quot;The challenge remains.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Turn a short challenge into a long one.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:30355,&quot;achieved_percent&quot;:0.0010641721205414808,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-when-you-see-it.png&quot;,&quot;id&quot;:287,&quot;name&quot;:&quot;When You See It&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-when-you-see-it&quot;,&quot;description&quot;:&quot;Three numbers which will haunt you forevermore.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;You don't need a hint for this one.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:5316,&quot;achieved_percent&quot;:0.000186365969125301,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-time-sink.png&quot;,&quot;id&quot;:300,&quot;name&quot;:&quot;Time Sink&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-time-sink&quot;,&quot;description&quot;:&quot;Rise from the depths into a new age.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Descend into the fathoms, yesteryear and today.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:726950,&quot;achieved_percent&quot;:0.025485090529653417,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-youre-here-forever.png&quot;,&quot;id&quot;:302,&quot;name&quot;:&quot;You're Here Forever&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-youre-here-forever&quot;,&quot;description&quot;:&quot;We knew you'd be back.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Touch grass.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:804127,&quot;achieved_percent&quot;:0.028190727549815824,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-hospitality.png&quot;,&quot;id&quot;:303,&quot;name&quot;:&quot;Hospitality&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-hospitality&quot;,&quot;description&quot;:&quot;Welcome.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;From guest, to host.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:5415,&quot;achieved_percent&quot;:0.0001898366671959189,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-true-north.png&quot;,&quot;id&quot;:304,&quot;name&quot;:&quot;True North&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-true-north&quot;,&quot;description&quot;:&quot;Where they tread, you go.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Seek your favourite creator to lead the way.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:12254,&quot;achieved_percent&quot;:0.0004295952945187055,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-superfan.png&quot;,&quot;id&quot;:306,&quot;name&quot;:&quot;Superfan&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-superfan&quot;,&quot;description&quot;:&quot;THIS IS MY JAM.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;AHHHHHH THEY'RE MY OSHI.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:7744,&quot;achieved_percent&quot;:0.0002714857157461119,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-resurgence.png&quot;,&quot;id&quot;:317,&quot;name&quot;:&quot;Resurgence&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-resurgence&quot;,&quot;description&quot;:&quot;A flame rekindled.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;From the ashes, blaze bright.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:8589,&quot;achieved_percent&quot;:0.0003011093507933052,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-clarity.png&quot;,&quot;id&quot;:318,&quot;name&quot;:&quot;Clarity&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-clarity&quot;,&quot;description&quot;:&quot;And yet in our memories, you remain crystal clear.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;A distorted reality and our own intersect.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:390541,&quot;achieved_percent&quot;:0.013691413082799883,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-autocreation.png&quot;,&quot;id&quot;:319,&quot;name&quot;:&quot;Autocreation&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-autocreation&quot;,&quot;description&quot;:&quot;Absolute rule.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;One is all.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3850,&quot;achieved_percent&quot;:0.00013497159163514087,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-festive.png&quot;,&quot;id&quot;:326,&quot;name&quot;:&quot;Festive Fever&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;osu-secret-festive&quot;,&quot;description&quot;:&quot;And the jingle bells never stop.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Well, eventually they do if you aren't careful enough.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:384775,&quot;achieved_percent&quot;:0.01348927121335359,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-identity.png&quot;,&quot;id&quot;:328,&quot;name&quot;:&quot;Value Your Identity&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-identity&quot;,&quot;description&quot;:&quot;As perfect as you are.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;In the end, you'll know what to do.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:86543,&quot;achieved_percent&quot;:0.006010742423195355,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-secret-dexterity.png&quot;,&quot;id&quot;:331,&quot;name&quot;:&quot;Dexterity&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;mania-secret-dexterity&quot;,&quot;description&quot;:&quot;True savants are flexible.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Don't go all in on one stat.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2578,&quot;achieved_percent&quot;:9.037838006114108e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-deciduousarborist.png&quot;,&quot;id&quot;:341,&quot;name&quot;:&quot;Deciduous Arborist&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-deciduousarborist&quot;,&quot;description&quot;:&quot;But life moves on.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;Break the cycle.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3385,&quot;achieved_percent&quot;:0.00011866982797011737,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-skinoftheteeth.png&quot;,&quot;id&quot;:346,&quot;name&quot;:&quot;By The Skin Of The Teeth&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-skinoftheteeth&quot;,&quot;description&quot;:&quot;You're that accurate.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;You said it yourself!&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1692,&quot;achieved_percent&quot;:5.931738520692425e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-infectiousenthusiasm.png&quot;,&quot;id&quot;:348,&quot;name&quot;:&quot;Infectious Enthusiasm&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-infectiousenthusiasm&quot;,&quot;description&quot;:&quot;You're a fungus.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;:)&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4830,&quot;achieved_percent&quot;:0.00016932799677863127,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-meticulousmayhem.png&quot;,&quot;id&quot;:349,&quot;name&quot;:&quot;Meticulous Mayhem&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-meticulousmayhem&quot;,&quot;description&quot;:&quot;How did we get here?&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;A curious brew, perceptually chaotic.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1499,&quot;achieved_percent&quot;:0.00012087287471578948,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/catch-secret-weatherreverie.png&quot;,&quot;id&quot;:351,&quot;name&quot;:&quot;Weather Reverie&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;catch-secret-weatherreverie&quot;,&quot;description&quot;:&quot;Up and above the world...&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;...Like a fruit tray in the sky.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:19329,&quot;achieved_percent&quot;:0.0006776275051209448,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-hotshot.png&quot;,&quot;id&quot;:353,&quot;name&quot;:&quot;Hotshot&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-hotshot&quot;,&quot;description&quot;:&quot;Star of the play, a masterpiece known the world over.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;Shine brighter than anyone else, in a way only you can.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:11608,&quot;achieved_percent&quot;:0.00040694811316901693,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-hamsterwheel.png&quot;,&quot;id&quot;:355,&quot;name&quot;:&quot;Hamster Wheel&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-hamsterwheel&quot;,&quot;description&quot;:&quot;Feeling dizzy yet?&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;Will it go any faster?&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:51815,&quot;achieved_percent&quot;:0.001816507278071383,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-couriercatapult.png&quot;,&quot;id&quot;:356,&quot;name&quot;:&quot;Courier Catapult&quot;,&quot;grouping&quot;:&quot;Hush-Hush&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-secret-couriercatapult&quot;,&quot;description&quot;:&quot;YEET!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;No spam mail, please!&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:960753,&quot;achieved_percent&quot;:0.0336816523579835,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-perseverance.png&quot;,&quot;id&quot;:132,&quot;name&quot;:&quot;Perseverance&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-perseverance&quot;,&quot;description&quot;:&quot;Endure.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Endurance is the key.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:30844,&quot;achieved_percent&quot;:0.001081315265556957,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-ftb.png&quot;,&quot;id&quot;:133,&quot;name&quot;:&quot;Feel The Burn&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-ftb&quot;,&quot;description&quot;:&quot;It isn't all about how fast you manage.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Endurance &lt;strong&gt;and&lt;\/strong&gt; precision is essential.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:48384,&quot;achieved_percent&quot;:0.0016962248025128976,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-onesecond.png&quot;,&quot;id&quot;:135,&quot;name&quot;:&quot;Just One Second&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-onesecond&quot;,&quot;description&quot;:&quot;And suddenly.. gone.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Blink and you'll miss it.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:41164,&quot;achieved_percent&quot;:0.0014431092462516724,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-challenge.png&quot;,&quot;id&quot;:143,&quot;name&quot;:&quot;Up For The Challenge&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-challenge&quot;,&quot;description&quot;:&quot;Turn it up to eleven.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Everything's better at eleven.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2452,&quot;achieved_percent&quot;:8.596112797126374e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-superhardhddt.png&quot;,&quot;id&quot;:145,&quot;name&quot;:&quot;Unstoppable&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-superhardhddt&quot;,&quot;description&quot;:&quot;Holy shit.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Reaching the limits of mortal skill.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1677,&quot;achieved_percent&quot;:5.879152186289123e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-supersuperhardhddt.png&quot;,&quot;id&quot;:146,&quot;name&quot;:&quot;Is This Real Life?&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-supersuperhardhddt&quot;,&quot;description&quot;:&quot;You did NOT just pull that off.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;The absolute height of perfection.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:11958,&quot;achieved_percent&quot;:0.0004192182578631206,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-realitat.png&quot;,&quot;id&quot;:155,&quot;name&quot;:&quot;Realit\u00e4t&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-realitat&quot;,&quot;description&quot;:&quot;A moonlight butterfly, and beacons of three.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Dream of greater heights.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:36562,&quot;achieved_percent&quot;:0.0012817743723023429,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-ourbenefactors.png&quot;,&quot;id&quot;:156,&quot;name&quot;:&quot;Our Mechanical Benefactors&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-ourbenefactors&quot;,&quot;description&quot;:&quot;Human, please explain directive \&quot;GREED\&quot;.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Close, yet so far.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:14905,&quot;achieved_percent&quot;:0.000522532876187474,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-elite.png&quot;,&quot;id&quot;:161,&quot;name&quot;:&quot;Elite&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-elite&quot;,&quot;description&quot;:&quot;Dangerous beat agents.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;A challenge for status, prestige and fame is not always the smartest thing to do in the middle of something.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:740758,&quot;achieved_percent&quot;:0.02596916526661394,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-5050.png&quot;,&quot;id&quot;:168,&quot;name&quot;:&quot;50\/50&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-5050&quot;,&quot;description&quot;:&quot;Half full or half empty, that's a whole lot of fifty.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Strong opinions about this, one way or another.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:23851,&quot;achieved_percent&quot;:0.0008361577745687648,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-thrillofthechase.png&quot;,&quot;id&quot;:170,&quot;name&quot;:&quot;Thrill of the Chase&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-thrillofthechase&quot;,&quot;description&quot;:&quot;My heart's beating, my hands are shaking, and I'm STILL clicking.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Is there anything better than the hunt? Such a classic pursuit.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:11319,&quot;achieved_percent&quot;:0.00039681647940731417,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-girlintheforest.png&quot;,&quot;id&quot;:171,&quot;name&quot;:&quot;The Girl in the Forest&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-girlintheforest&quot;,&quot;description&quot;:&quot;Not even the Elite Four could stop you now.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Think back to where it all began, in shades of red and blue..&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:13832,&quot;achieved_percent&quot;:0.0004849161183109788,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-youcanthide.png&quot;,&quot;id&quot;:172,&quot;name&quot;:&quot;You Can't Hide&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-youcanthide&quot;,&quot;description&quot;:&quot;I will find you, and I will click you. All of you.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Don't even try to hide.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:5366,&quot;achieved_percent&quot;:0.0001881188469387444,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-truetorment.png&quot;,&quot;id&quot;:173,&quot;name&quot;:&quot;True Torment&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-truetorment&quot;,&quot;description&quot;:&quot;It lasts forever.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Note the ghosts.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:18523,&quot;achieved_percent&quot;:0.0006493711147682375,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-celestialmovement.png&quot;,&quot;id&quot;:174,&quot;name&quot;:&quot;The Firmament Moves&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-celestialmovement&quot;,&quot;description&quot;:&quot;Number fourteen? More like number one.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Three times does it move, but most only know one. What you seek is something different yet again, warped three times over.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:151637,&quot;achieved_percent&quot;:0.005316022659942301,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-toofasttoofurious.png&quot;,&quot;id&quot;:175,&quot;name&quot;:&quot;Too Fast, Too Furious&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-toofasttoofurious&quot;,&quot;description&quot;:&quot;A march if you have eight feet, maybe!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Something you don't do when you're afraid.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:5354843,&quot;achieved_percent&quot;:0.18772770978345263,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-feelinit.png&quot;,&quot;id&quot;:176,&quot;name&quot;:&quot;Feelin' It&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-feelinit&quot;,&quot;description&quot;:&quot;Got with the times.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Beats multiplied. A lot of them.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1010734,&quot;achieved_percent&quot;:0.035433864077857785,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-overconfident.png&quot;,&quot;id&quot;:177,&quot;name&quot;:&quot;Overconfident&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-overconfident&quot;,&quot;description&quot;:&quot;Try again later, maybe?&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;The 's' in progress stands for hubris.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:174892,&quot;achieved_percent&quot;:0.00613128613097482,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-spooked.png&quot;,&quot;id&quot;:178,&quot;name&quot;:&quot;Spooked&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-spooked&quot;,&quot;description&quot;:&quot;Something moved. It wasn't your cursor!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Don't look behind you.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:195,&quot;achieved_percent&quot;:6.836223472429213e-6,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-skylord.png&quot;,&quot;id&quot;:192,&quot;name&quot;:&quot;Skylord&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-skylord&quot;,&quot;description&quot;:&quot;Never miss a wingbeat.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Flight among the sky requires nothing but perfection.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4078,&quot;achieved_percent&quot;:0.00014296471446444272,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-brave.png&quot;,&quot;id&quot;:193,&quot;name&quot;:&quot;B-Rave&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-brave&quot;,&quot;description&quot;:&quot;It takes courage to stand before the master.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Ill-tempered bosses make for excellent final battles.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:37206,&quot;achieved_percent&quot;:0.0013043514385394938,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-anypercent.png&quot;,&quot;id&quot;:194,&quot;name&quot;:&quot;Any%&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-anypercent&quot;,&quot;description&quot;:&quot;A speedrunner's best friend.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Sometimes you have to break the rules to work with speed.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:732,&quot;achieved_percent&quot;:2.5662131188811197e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-mirage.png&quot;,&quot;id&quot;:195,&quot;name&quot;:&quot;Mirage&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-mirage&quot;,&quot;description&quot;:&quot;The horizon goes on forever, and ever, and ever...&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;The light is far harder than it seems.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2518,&quot;achieved_percent&quot;:8.827492668500902e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-underthestars.png&quot;,&quot;id&quot;:196,&quot;name&quot;:&quot;Under The Stars&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-underthestars&quot;,&quot;description&quot;:&quot;Onwards, to where the darkness can never stop us.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Walk beneath the stars on a journey to elsewhere.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:13596,&quot;achieved_percent&quot;:0.000476642535031526,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-senseless.png&quot;,&quot;id&quot;:197,&quot;name&quot;:&quot;Senseless&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-senseless&quot;,&quot;description&quot;:&quot;I hear nothing. I see nothing.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;A song that is, and something that is not.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:11380,&quot;achieved_percent&quot;:0.0003989549903397151,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-uponthewind.png&quot;,&quot;id&quot;:200,&quot;name&quot;:&quot;Upon The Wind&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-uponthewind&quot;,&quot;description&quot;:&quot;And in that gale, no eye could hope to follow.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;In the heart of a storm of flowers, a world unseen.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:11020,&quot;achieved_percent&quot;:0.00038633427008292267,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-vantage.png&quot;,&quot;id&quot;:201,&quot;name&quot;:&quot;Vantage&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-vantage&quot;,&quot;description&quot;:&quot;There we stood, where the spires pierced the sky, and dreamed of the future to come.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Where ground was broken to critical acclaim.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:15326,&quot;achieved_percent&quot;:0.0005372921073766672,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-efflorescence.png&quot;,&quot;id&quot;:204,&quot;name&quot;:&quot;Efflorescence&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-efflorescence&quot;,&quot;description&quot;:&quot;A lament for the past, and a glimpse into tomorrow.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;The horizon thunders with a portentous bloom.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:6093,&quot;achieved_percent&quot;:0.00021360569034621125,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-inundate.png&quot;,&quot;id&quot;:216,&quot;name&quot;:&quot;Inundate&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-inundate&quot;,&quot;description&quot;:&quot;Swept away.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Across and beyond the tides.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:158,&quot;achieved_percent&quot;:5.539093890481106e-6,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-bluffing.png&quot;,&quot;id&quot;:217,&quot;name&quot;:&quot;Not Bluffing&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-bluffing&quot;,&quot;description&quot;:&quot;Did that with my eyes closed.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;It's not arrogance if you can live up to it.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:8229,&quot;achieved_percent&quot;:0.00028848863053651275,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-eureka.png&quot;,&quot;id&quot;:218,&quot;name&quot;:&quot;Eureka!&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-eureka&quot;,&quot;description&quot;:&quot;By Jove, you've got it!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;When inspiration strikes...&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1950,&quot;achieved_percent&quot;:6.836223472429213e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-regicide.png&quot;,&quot;id&quot;:219,&quot;name&quot;:&quot;Regicide&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-regicide&quot;,&quot;description&quot;:&quot;A king no more.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;No throne lasts forever.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4186,&quot;achieved_percent&quot;:0.00014675093054148042,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-permadeath.png&quot;,&quot;id&quot;:220,&quot;name&quot;:&quot;Permadeath&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-permadeath&quot;,&quot;description&quot;:&quot;One life, one shot.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Better make it count! Ware well the example of the white cat.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:16737,&quot;achieved_percent&quot;:0.0005867583192720396,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-futureisnow.png&quot;,&quot;id&quot;:221,&quot;name&quot;:&quot;The Future Is Now&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-futureisnow&quot;,&quot;description&quot;:&quot;The stars showed you all that was to come.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Withstand the primordial.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:283197,&quot;achieved_percent&quot;:0.009928194762674543,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-nat20.png&quot;,&quot;id&quot;:222,&quot;name&quot;:&quot;Natural 20&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-nat20&quot;,&quot;description&quot;:&quot;Rolled it.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Not just a chance of the dice, this one is all skill.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:105562,&quot;achieved_percent&quot;:0.0037007457548542183,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-deadcenter.png&quot;,&quot;id&quot;:276,&quot;name&quot;:&quot;Dead Center&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-deadcenter&quot;,&quot;description&quot;:&quot;As all things should be.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Perfect balance.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1516,&quot;achieved_percent&quot;:5.314725530360352e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-finalboss.png&quot;,&quot;id&quot;:280,&quot;name&quot;:&quot;Final Boss&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-finalboss&quot;,&quot;description&quot;:&quot;Game over.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Let the credits roll.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:9123,&quot;achieved_percent&quot;:0.0003198300858408806,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-yandere.png&quot;,&quot;id&quot;:224,&quot;name&quot;:&quot;AHAHAHAHA&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-yandere&quot;,&quot;description&quot;:&quot;TOGETHER FOREVER.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Who am I? Where am I? What the hell IS this place?&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:543,&quot;achieved_percent&quot;:1.9036253053995193e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-beastmode.png&quot;,&quot;id&quot;:281,&quot;name&quot;:&quot;Beast Mode&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-beastmode&quot;,&quot;description&quot;:&quot;Unleash the animal within!&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Go absolutely feral.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1612,&quot;achieved_percent&quot;:5.651278070541482e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-lightless.png&quot;,&quot;id&quot;:286,&quot;name&quot;:&quot;Lightless&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-lightless&quot;,&quot;description&quot;:&quot;Better the devil you know.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;I CAN'T SEE A THING.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:23133,&quot;achieved_percent&quot;:0.0008109864491677179,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-together-apart.png&quot;,&quot;id&quot;:297,&quot;name&quot;:&quot;Mortal Coils&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-together-apart&quot;,&quot;description&quot;:&quot;Never one without the other.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Prisoners of flesh in an unending apocalypse.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1325,&quot;achieved_percent&quot;:4.645126205624978e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-dark-familiarity.png&quot;,&quot;id&quot;:298,&quot;name&quot;:&quot;Dark Familiarity&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-dark-familiarity&quot;,&quot;description&quot;:&quot;No mistakes, no witnesses.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Don't second guess yourself.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4930,&quot;achieved_percent&quot;:0.00017283375240551805,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-trophy.png&quot;,&quot;id&quot;:299,&quot;name&quot;:&quot;Creator's Gambit&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-trophy&quot;,&quot;description&quot;:&quot;I made this.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Make your own prize.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:14868,&quot;achieved_percent&quot;:0.0005212357466055258,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-unseen-heights.png&quot;,&quot;id&quot;:301,&quot;name&quot;:&quot;Unseen Heights&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-unseen-heights&quot;,&quot;description&quot;:&quot;Reach for the stars.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Go where even the editor fears to tread.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1141,&quot;achieved_percent&quot;:4.000067170277811e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-astronomic.png&quot;,&quot;id&quot;:305,&quot;name&quot;:&quot;Astronomic&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-astronomic&quot;,&quot;description&quot;:&quot;Precision machinery.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Celestial coordinates: 284-905.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1477,&quot;achieved_percent&quot;:5.178001060911768e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-iron-will.png&quot;,&quot;id&quot;:307,&quot;name&quot;:&quot;Iron Will&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-iron-will&quot;,&quot;description&quot;:&quot;A legacy of broken bonds, remade.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Step forth, and master three years of titan-ending tests.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2080,&quot;achieved_percent&quot;:7.291971703924494e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-star-power.png&quot;,&quot;id&quot;:320,&quot;name&quot;:&quot;Star Power&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-star-power&quot;,&quot;description&quot;:&quot;AND I'LL DO IT AGAIN.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;When an encore just isn't enough.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:6927,&quot;achieved_percent&quot;:0.00024284369227444696,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-causality.png&quot;,&quot;id&quot;:321,&quot;name&quot;:&quot;Causality&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-causality&quot;,&quot;description&quot;:&quot;Definitely not for casuals.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Flee from the future.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:2147,&quot;achieved_percent&quot;:7.526857330925907e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-abrogation.png&quot;,&quot;id&quot;:322,&quot;name&quot;:&quot;Abrogation&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-abrogation&quot;,&quot;description&quot;:&quot;Endure not the imposition of celestial law.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Return to whence the rules were first broken.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1066,&quot;achieved_percent&quot;:3.737135498261303e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-internment.png&quot;,&quot;id&quot;:323,&quot;name&quot;:&quot;Internment&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-internment&quot;,&quot;description&quot;:&quot;Stained in the hues of madness, they rage within a four-walled jail.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;a href=\&quot;https:\/\/assets.ppy.sh\/medals\/internment_hint.jpg\&quot;&gt;&lt;i&gt;Bask in the shade of an ailing mind.&lt;\/i&gt;&lt;\/a&gt;&quot;},{&quot;achieved_count&quot;:274,&quot;achieved_percent&quot;:1.950258861275169e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-secret-anabasis.png&quot;,&quot;id&quot;:324,&quot;name&quot;:&quot;Anabasis&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;taiko-secret-anabasis&quot;,&quot;description&quot;:&quot;And what an adventure you had.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Life is but a journey of the senses.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1385,&quot;achieved_percent&quot;:9.858060302431055e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-secret-literal.png&quot;,&quot;id&quot;:327,&quot;name&quot;:&quot;Literal&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;taiko-secret-literal&quot;,&quot;description&quot;:&quot;The instructions were very clear.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;...but probably not optimal.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3316,&quot;achieved_percent&quot;:0.0002673878936341281,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/catch-secret-banana.png&quot;,&quot;id&quot;:329,&quot;name&quot;:&quot;Banana Republic&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;catch-secret-banana&quot;,&quot;description&quot;:&quot;Potassium overdose.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;The more may not always be the merrier.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:321,&quot;achieved_percent&quot;:1.125347556230655e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-hybrid.png&quot;,&quot;id&quot;:332,&quot;name&quot;:&quot;Hybrid Hyperion&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-hybrid&quot;,&quot;description&quot;:&quot;Manifold conqueror.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;You proteans should show off more.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:587,&quot;achieved_percent&quot;:2.0578785529825372e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-divinationbreak.png&quot;,&quot;id&quot;:333,&quot;name&quot;:&quot;Divination Break&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-divinationbreak&quot;,&quot;description&quot;:&quot;So cold...&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;The frozen thread shattered.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:106997,&quot;achieved_percent&quot;:0.0037510533481000434,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-unwilted.png&quot;,&quot;id&quot;:334,&quot;name&quot;:&quot;Unwilted&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-unwilted&quot;,&quot;description&quot;:&quot;Vivid recollection of a forgotten memory.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Flourish anew like it was yesterday.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:173,&quot;achieved_percent&quot;:6.064957234514122e-6,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-secret-pioneer.png&quot;,&quot;id&quot;:342,&quot;name&quot;:&quot;Pioneer&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;all-secret-pioneer&quot;,&quot;description&quot;:&quot;Call sign: Cedar&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;i&gt;Liftoff schedule at subunit precision.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:960,&quot;achieved_percent&quot;:3.3655254018113044e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-overcooked.png&quot;,&quot;id&quot;:343,&quot;name&quot;:&quot;Overcooked?&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-overcooked&quot;,&quot;description&quot;:&quot;Come and watch me!&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Internet lemonade!&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:287,&quot;achieved_percent&quot;:2.0427893911896842e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-secret-stargazer.png&quot;,&quot;id&quot;:344,&quot;name&quot;:&quot;Stargazer&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;taiko-secret-stargazer&quot;,&quot;description&quot;:&quot;Three for the almanac.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Return later.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:842,&quot;achieved_percent&quot;:2.951846237838665e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-candescence.png&quot;,&quot;id&quot;:345,&quot;name&quot;:&quot;Candescence&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-candescence&quot;,&quot;description&quot;:&quot;Guided by blazing resolve.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;Allow no shortcuts.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:571,&quot;achieved_percent&quot;:2.001786462952349e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-icefairy.png&quot;,&quot;id&quot;:347,&quot;name&quot;:&quot;The Strongest Ice Fairy&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-icefairy&quot;,&quot;description&quot;:&quot;Extreme Sign \&quot;Perfect Metal\&quot;&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;Unfazed by eidetic patterns.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3460,&quot;achieved_percent&quot;:0.00012129914469028244,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-uptoeleven.png&quot;,&quot;id&quot;:352,&quot;name&quot;:&quot;Up To Eleven&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-uptoeleven&quot;,&quot;description&quot;:&quot;Crank it up!&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;Break limits.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:3491,&quot;achieved_percent&quot;:0.00012238592893461735,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-waningmemory.png&quot;,&quot;id&quot;:357,&quot;name&quot;:&quot;Waning Memory&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-waningmemory&quot;,&quot;description&quot;:&quot;An image reformed.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Concealed reflection or genuine recollection.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:6281,&quot;achieved_percent&quot;:0.0002201965109247584,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-secret-fadingreflection.png&quot;,&quot;id&quot;:358,&quot;name&quot;:&quot;Fading Reflection&quot;,&quot;grouping&quot;:&quot;Hush-Hush (Expert)&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;osu-secret-fadingreflection&quot;,&quot;description&quot;:&quot;A falsehood adorned.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Fabricated memory or unveiled identity.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:1142095,&quot;achieved_percent&quot;:0.04003905972689252,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-suddendeath.png&quot;,&quot;id&quot;:119,&quot;name&quot;:&quot;Finality&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-suddendeath&quot;,&quot;description&quot;:&quot;High stakes, no regrets.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;completing a map with the &lt;b&gt;Sudden Death&lt;\/b&gt; mod enabled!&quot;},{&quot;achieved_count&quot;:675678,&quot;achieved_percent&quot;:0.023687619504636027,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-perfect.png&quot;,&quot;id&quot;:120,&quot;name&quot;:&quot;Perfectionist&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-perfect&quot;,&quot;description&quot;:&quot;Accept nothing but the best.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;completing a map with the &lt;b&gt;Perfect&lt;\/b&gt; mod enabled!&quot;},{&quot;achieved_count&quot;:3631183,&quot;achieved_percent&quot;:0.12730040234505602,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-hardrock.png&quot;,&quot;id&quot;:121,&quot;name&quot;:&quot;Rock Around The Clock&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-hardrock&quot;,&quot;description&quot;:&quot;You can't stop the rock.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;completing a map with the &lt;b&gt;Hard Rock&lt;\/b&gt; mod enabled!&quot;},{&quot;achieved_count&quot;:3244404,&quot;achieved_percent&quot;:0.11374087578893963,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-doubletime.png&quot;,&quot;id&quot;:122,&quot;name&quot;:&quot;Time And A Half&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-doubletime&quot;,&quot;description&quot;:&quot;Having a right ol' time. One and a half of them, almost.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;completing a map with the &lt;b&gt;DoubleTime&lt;\/b&gt; mod enabled!&quot;},{&quot;achieved_count&quot;:2242881,&quot;achieved_percent&quot;:0.07862992686187438,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-nightcore.png&quot;,&quot;id&quot;:123,&quot;name&quot;:&quot;Sweet Rave Party&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-nightcore&quot;,&quot;description&quot;:&quot;Founded in the fine tradition of changing things that were just fine as they were.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;completing a map with the &lt;b&gt;Nightcore&lt;\/b&gt; mod enabled!&quot;},{&quot;achieved_count&quot;:1970565,&quot;achieved_percent&quot;:0.06908319336896139,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-hidden.png&quot;,&quot;id&quot;:124,&quot;name&quot;:&quot;Blindsight&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-hidden&quot;,&quot;description&quot;:&quot;I can see just perfectly.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;completing a map with the &lt;b&gt;Hidden&lt;\/b&gt; mod enabled!&quot;},{&quot;achieved_count&quot;:949242,&quot;achieved_percent&quot;:0.03327810482777257,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-flashlight.png&quot;,&quot;id&quot;:125,&quot;name&quot;:&quot;Are You Afraid Of The Dark?&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-flashlight&quot;,&quot;description&quot;:&quot;Harder than it looks, probably because it's hard to look.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;completing a map with the &lt;b&gt;Flashlight&lt;\/b&gt; mod enabled!&quot;},{&quot;achieved_count&quot;:1884975,&quot;achieved_percent&quot;:0.066082617127909,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-easy.png&quot;,&quot;id&quot;:126,&quot;name&quot;:&quot;Dial It Right Back&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-easy&quot;,&quot;description&quot;:&quot;Sometimes you just want to take it easy.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;completing a map with the &lt;b&gt;Easy&lt;\/b&gt; mod enabled!&quot;},{&quot;achieved_count&quot;:5440702,&quot;achieved_percent&quot;:0.19073771650714136,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-nofail.png&quot;,&quot;id&quot;:127,&quot;name&quot;:&quot;Risk Averse&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-nofail&quot;,&quot;description&quot;:&quot;Safety nets are fun!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;completing a map with the &lt;b&gt;No Fail&lt;\/b&gt; mod enabled!&quot;},{&quot;achieved_count&quot;:1103326,&quot;achieved_percent&quot;:0.03867991332790479,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-halftime.png&quot;,&quot;id&quot;:128,&quot;name&quot;:&quot;Slowboat&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-halftime&quot;,&quot;description&quot;:&quot;You got there. Eventually.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;completing a map with the &lt;b&gt;HalfTime&lt;\/b&gt; mod enabled!&quot;},{&quot;achieved_count&quot;:568898,&quot;achieved_percent&quot;:0.01994417364624633,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-spunout.png&quot;,&quot;id&quot;:131,&quot;name&quot;:&quot;Burned Out&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-spunout&quot;,&quot;description&quot;:&quot;One cannot always spin to win.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;completing a map with the &lt;b&gt;Spun Out&lt;\/b&gt; mod enabled!&quot;},{&quot;achieved_count&quot;:242983,&quot;achieved_percent&quot;:0.008518390194878295,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-conversion.png&quot;,&quot;id&quot;:339,&quot;name&quot;:&quot;Gear Shift&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-conversion&quot;,&quot;description&quot;:&quot;Tailor your experience to your perfect fit.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;Complete a map with any &lt;b&gt;Conversion&lt;\/b&gt; mod enabled.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:104487,&quot;achieved_percent&quot;:0.0036630588818651853,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-intro-fun.png&quot;,&quot;id&quot;:340,&quot;name&quot;:&quot;Game Night&quot;,&quot;grouping&quot;:&quot;Mod Introduction&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;all-intro-fun&quot;,&quot;description&quot;:&quot;Mum said it's my turn with the beatmap!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;Complete a map with any &lt;b&gt;Fun&lt;\/b&gt; mod enabled.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:4895332,&quot;achieved_percent&quot;:0.17161837704478894,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-combo-500.png&quot;,&quot;id&quot;:1,&quot;name&quot;:&quot;500 Combo&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;osu-combo-500&quot;,&quot;description&quot;:&quot;500 big ones! You're moving up in the world!&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;aiming for a combo of 500 or higher on any beatmap&quot;},{&quot;achieved_count&quot;:2203535,&quot;achieved_percent&quot;:0.07725055225291952,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-combo-750.png&quot;,&quot;id&quot;:3,&quot;name&quot;:&quot;750 Combo&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;osu-combo-750&quot;,&quot;description&quot;:&quot;750 notes back to back? Woah.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;aiming for a combo of 750 or higher on any beatmap&quot;},{&quot;achieved_count&quot;:1082668,&quot;achieved_percent&quot;:0.03795569433050252,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-combo-1000.png&quot;,&quot;id&quot;:4,&quot;name&quot;:&quot;1,000 Combo&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;osu-combo-1000&quot;,&quot;description&quot;:&quot;A thousand reasons why you rock at this game.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;aiming for a combo of at least 1,000 on any beatmap (try a &lt;a href='\/p\/beatmaplist?q=marathon'&gt;marathon&lt;\/a&gt;)&quot;},{&quot;achieved_count&quot;:164244,&quot;achieved_percent&quot;:0.005757993271823916,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-combo-2000.png&quot;,&quot;id&quot;:5,&quot;name&quot;:&quot;2,000 Combo&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:0,&quot;slug&quot;:&quot;osu-combo-2000&quot;,&quot;description&quot;:&quot;Nothing can stop you now.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;aiming for a combo of at least 2,000 on any beatmap (try a &lt;a href='\/p\/beatmaplist?q=marathon'&gt;marathon&lt;\/a&gt;)&quot;},{&quot;achieved_count&quot;:1146187,&quot;achieved_percent&quot;:0.04018251524714473,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-plays-5000.png&quot;,&quot;id&quot;:20,&quot;name&quot;:&quot;5,000 Plays&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:1,&quot;slug&quot;:&quot;osu-plays-5000&quot;,&quot;description&quot;:&quot;There's a lot more where that came from.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:384094,&quot;achieved_percent&quot;:0.013465397017534492,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-plays-15000.png&quot;,&quot;id&quot;:21,&quot;name&quot;:&quot;15,000 Plays&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:1,&quot;slug&quot;:&quot;osu-plays-15000&quot;,&quot;description&quot;:&quot;Must.. click.. circles..&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:204101,&quot;achieved_percent&quot;:0.007155282292032179,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-plays-25000.png&quot;,&quot;id&quot;:22,&quot;name&quot;:&quot;25,000 Plays&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:1,&quot;slug&quot;:&quot;osu-plays-25000&quot;,&quot;description&quot;:&quot;There's no going back.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:70482,&quot;achieved_percent&quot;:0.0024709266809423373,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-plays-50000.png&quot;,&quot;id&quot;:28,&quot;name&quot;:&quot;50,000 Plays&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:1,&quot;slug&quot;:&quot;osu-plays-50000&quot;,&quot;description&quot;:&quot;You're here forever.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:583443,&quot;achieved_percent&quot;:0.020454085802177013,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-skill-highranker-1.png&quot;,&quot;id&quot;:50,&quot;name&quot;:&quot;I Can See The Top&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-skill-highranker-1&quot;,&quot;description&quot;:&quot;Your dedication has paid off. Welcome to the top 50,000!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:128565,&quot;achieved_percent&quot;:0.004507174721706983,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-skill-highranker-2.png&quot;,&quot;id&quot;:51,&quot;name&quot;:&quot;The Gradual Rise&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-skill-highranker-2&quot;,&quot;description&quot;:&quot;There's no stopping you, is there? Welcome to the top 10,000!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:67663,&quot;achieved_percent&quot;:0.0023720994298203992,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-skill-highranker-3.png&quot;,&quot;id&quot;:52,&quot;name&quot;:&quot;Scaling Up&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-skill-highranker-3&quot;,&quot;description&quot;:&quot;Welcome to the top 5,000. Never give up!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:16641,&quot;achieved_percent&quot;:0.0005833927938702283,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-skill-highranker-4.png&quot;,&quot;id&quot;:53,&quot;name&quot;:&quot;Approaching The Summit&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:2,&quot;slug&quot;:&quot;all-skill-highranker-4&quot;,&quot;description&quot;:&quot;Pro tier. Welcome to the top 1,000!&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:635693,&quot;achieved_percent&quot;:0.051259533253305116,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-hits-20000.png&quot;,&quot;id&quot;:13,&quot;name&quot;:&quot;Catch 20,000 fruits&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;fruits-hits-20000&quot;,&quot;description&quot;:&quot;That is a lot of dietary fiber.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:239933,&quot;achieved_percent&quot;:0.017077790487676464,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-hits-30000.png&quot;,&quot;id&quot;:31,&quot;name&quot;:&quot;30,000 Drum Hits&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;taiko-hits-30000&quot;,&quot;description&quot;:&quot;Did that drum have a face?&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1580291,&quot;achieved_percent&quot;:0.10975725540706714,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-hits-40000.png&quot;,&quot;id&quot;:46,&quot;name&quot;:&quot;40,000 Keys&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;mania-hits-40000&quot;,&quot;description&quot;:&quot;Just the start of the rainbow.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:131559,&quot;achieved_percent&quot;:0.010608348582211173,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-hits-200000.png&quot;,&quot;id&quot;:23,&quot;name&quot;:&quot;Catch 200,000 fruits&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;fruits-hits-200000&quot;,&quot;description&quot;:&quot;So, I heard you like fruit...&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:49864,&quot;achieved_percent&quot;:0.0035491864181979933,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-hits-300000.png&quot;,&quot;id&quot;:32,&quot;name&quot;:&quot;300,000 Drum Hits&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;taiko-hits-300000&quot;,&quot;description&quot;:&quot;The rhythm never stops.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:523452,&quot;achieved_percent&quot;:0.036355743883462036,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-hits-400000.png&quot;,&quot;id&quot;:47,&quot;name&quot;:&quot;400,000 Keys&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;mania-hits-400000&quot;,&quot;description&quot;:&quot;Four hundred thousand and still not even close.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:18325,&quot;achieved_percent&quot;:0.0014776487185902884,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-hits-2000000.png&quot;,&quot;id&quot;:24,&quot;name&quot;:&quot;Catch 2,000,000 fruits&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;fruits-hits-2000000&quot;,&quot;description&quot;:&quot;Downright healthy.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:8555,&quot;achieved_percent&quot;:0.0006089220641682143,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-hits-3000000.png&quot;,&quot;id&quot;:33,&quot;name&quot;:&quot;3,000,000 Drum Hits&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;taiko-hits-3000000&quot;,&quot;description&quot;:&quot;Truly, the Don of dons.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:75940,&quot;achieved_percent&quot;:0.0052743235110575696,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-hits-4000000.png&quot;,&quot;id&quot;:48,&quot;name&quot;:&quot;4,000,000 Keys&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;mania-hits-4000000&quot;,&quot;description&quot;:&quot;Is this the end of the rainbow?&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:273,&quot;achieved_percent&quot;:1.9431411282048217e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-hits-30000000.png&quot;,&quot;id&quot;:291,&quot;name&quot;:&quot;30,000,000 Drum Hits&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;taiko-hits-30000000&quot;,&quot;description&quot;:&quot;Your rhythm, eternal.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1397,&quot;achieved_percent&quot;:0.00011264803600931148,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-hits-20000000.png&quot;,&quot;id&quot;:292,&quot;name&quot;:&quot;Catch 20,000,000 fruits&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;fruits-hits-20000000&quot;,&quot;description&quot;:&quot;Nothing left behind.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:2264,&quot;achieved_percent&quot;:0.00015724346100914324,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-hits-40000000.png&quot;,&quot;id&quot;:293,&quot;name&quot;:&quot;40,000,000 Keys&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:3,&quot;slug&quot;:&quot;mania-hits-40000000&quot;,&quot;description&quot;:&quot;When someone asks which keys you play, the answer is now 'yes'.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:16708310,&quot;achieved_percent&quot;:0.5857525179826858,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-pass-1.png&quot;,&quot;id&quot;:55,&quot;name&quot;:&quot;Rising Star&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;osu-skill-pass-1&quot;,&quot;description&quot;:&quot;Can't go forward without the first steps.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:3616959,&quot;achieved_percent&quot;:0.2574454868839042,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-pass-1.png&quot;,&quot;id&quot;:71,&quot;name&quot;:&quot;My First Don&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;taiko-skill-pass-1&quot;,&quot;description&quot;:&quot;Marching to the beat of your own drum. Literally.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:4529339,&quot;achieved_percent&quot;:0.36522630119568994,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-pass-1.png&quot;,&quot;id&quot;:79,&quot;name&quot;:&quot;A Slice Of Life&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;fruits-skill-pass-1&quot;,&quot;description&quot;:&quot;Hey, this fruit catching business isn't bad.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:5384285,&quot;achieved_percent&quot;:0.37395919101573094,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-pass-1.png&quot;,&quot;id&quot;:87,&quot;name&quot;:&quot;First Steps&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;mania-skill-pass-1&quot;,&quot;description&quot;:&quot;It isn't 9-to-5, but 1-to-9. Keys, that is.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:12471747,&quot;achieved_percent&quot;:0.43722897222358265,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-pass-2.png&quot;,&quot;id&quot;:56,&quot;name&quot;:&quot;Constellation Prize&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;osu-skill-pass-2&quot;,&quot;description&quot;:&quot;Definitely not a consolation prize. Now things start getting hard!&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1629139,&quot;achieved_percent&quot;:0.11595776536492582,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-pass-2.png&quot;,&quot;id&quot;:72,&quot;name&quot;:&quot;Katsu Katsu Katsu&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;taiko-skill-pass-2&quot;,&quot;description&quot;:&quot;Hora! Ikuzo!&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:719149,&quot;achieved_percent&quot;:0.05798906402867598,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-pass-2.png&quot;,&quot;id&quot;:80,&quot;name&quot;:&quot;Dashing Ever Forward&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;fruits-skill-pass-2&quot;,&quot;description&quot;:&quot;Fast is how you do it.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:2120509,&quot;achieved_percent&quot;:0.14727746212943346,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-pass-2.png&quot;,&quot;id&quot;:88,&quot;name&quot;:&quot;No Normal Player&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;mania-skill-pass-2&quot;,&quot;description&quot;:&quot;Not anymore, at least.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:5815835,&quot;achieved_percent&quot;:0.20388896276295052,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-pass-3.png&quot;,&quot;id&quot;:57,&quot;name&quot;:&quot;Building Confidence&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;osu-skill-pass-3&quot;,&quot;description&quot;:&quot;Oh, you've SO got this.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:280202,&quot;achieved_percent&quot;:0.019944030417774632,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-pass-3.png&quot;,&quot;id&quot;:73,&quot;name&quot;:&quot;Not Even Trying&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;taiko-skill-pass-3&quot;,&quot;description&quot;:&quot;Muzukashii? Not even.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:90591,&quot;achieved_percent&quot;:0.007304866306456361,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-pass-3.png&quot;,&quot;id&quot;:81,&quot;name&quot;:&quot;Zesty Disposition&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;fruits-skill-pass-3&quot;,&quot;description&quot;:&quot;No scurvy for you, not with that much fruit.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:990456,&quot;achieved_percent&quot;:0.06879095822317667,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-pass-3.png&quot;,&quot;id&quot;:89,&quot;name&quot;:&quot;Impulse Drive&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;mania-skill-pass-3&quot;,&quot;description&quot;:&quot;Not quite hyperspeed, but getting close.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:3152196,&quot;achieved_percent&quot;:0.11050828864049987,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-pass-4.png&quot;,&quot;id&quot;:58,&quot;name&quot;:&quot;Insanity Approaches&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;osu-skill-pass-4&quot;,&quot;description&quot;:&quot;You're not twitching, you're just ready.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:91704,&quot;achieved_percent&quot;:0.0065272459348313175,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-pass-4.png&quot;,&quot;id&quot;:74,&quot;name&quot;:&quot;Face Your Demons&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;taiko-skill-pass-4&quot;,&quot;description&quot;:&quot;The first trials are now behind you, but are you a match for the Oni?&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:30741,&quot;achieved_percent&quot;:0.002478821241920003,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-pass-4.png&quot;,&quot;id&quot;:82,&quot;name&quot;:&quot;Hyperdash ON!&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;fruits-skill-pass-4&quot;,&quot;description&quot;:&quot;Time and distance is no obstacle to you.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:476957,&quot;achieved_percent&quot;:0.03312648826525527,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-pass-4.png&quot;,&quot;id&quot;:90,&quot;name&quot;:&quot;Hyperspeed&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;mania-skill-pass-4&quot;,&quot;description&quot;:&quot;Woah.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1795168,&quot;achieved_percent&quot;:0.0629342031720708,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-pass-5.png&quot;,&quot;id&quot;:59,&quot;name&quot;:&quot;These Clarion Skies&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;osu-skill-pass-5&quot;,&quot;description&quot;:&quot;Everything seems so clear now.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:45170,&quot;achieved_percent&quot;:0.00321508002787589,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-pass-5.png&quot;,&quot;id&quot;:75,&quot;name&quot;:&quot;The Demon Within&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;taiko-skill-pass-5&quot;,&quot;description&quot;:&quot;No rest for the wicked.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:12722,&quot;achieved_percent&quot;:0.0010258470394491487,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-pass-5.png&quot;,&quot;id&quot;:83,&quot;name&quot;:&quot;It's Raining Fruit&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;fruits-skill-pass-5&quot;,&quot;description&quot;:&quot;And you can catch them all.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:191352,&quot;achieved_percent&quot;:0.013290128423596104,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-pass-5.png&quot;,&quot;id&quot;:91,&quot;name&quot;:&quot;Ever Onwards&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;mania-skill-pass-5&quot;,&quot;description&quot;:&quot;Another challenge is just around the corner.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:850687,&quot;achieved_percent&quot;:0.029823007369694305,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-pass-6.png&quot;,&quot;id&quot;:60,&quot;name&quot;:&quot;Above and Beyond&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;osu-skill-pass-6&quot;,&quot;description&quot;:&quot;A cut above the rest.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:19960,&quot;achieved_percent&quot;:0.0014206995208413274,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-pass-6.png&quot;,&quot;id&quot;:76,&quot;name&quot;:&quot;Drumbreaker&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;taiko-skill-pass-6&quot;,&quot;description&quot;:&quot;Too strong.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:6299,&quot;achieved_percent&quot;:0.0005079241079618132,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-pass-6.png&quot;,&quot;id&quot;:84,&quot;name&quot;:&quot;Fruit Ninja&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;fruits-skill-pass-6&quot;,&quot;description&quot;:&quot;Legendary techniques.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:91196,&quot;achieved_percent&quot;:0.006333911073405401,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-pass-6.png&quot;,&quot;id&quot;:92,&quot;name&quot;:&quot;Another Surpassed&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;mania-skill-pass-6&quot;,&quot;description&quot;:&quot;Is there no limit to your skills?&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:382480,&quot;achieved_percent&quot;:0.01340881412171654,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-pass-7.png&quot;,&quot;id&quot;:61,&quot;name&quot;:&quot;Supremacy&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;osu-skill-pass-7&quot;,&quot;description&quot;:&quot;All marvel before your prowess.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:10982,&quot;achieved_percent&quot;:0.000781669445785544,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-pass-7.png&quot;,&quot;id&quot;:77,&quot;name&quot;:&quot;The Godfather&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;taiko-skill-pass-7&quot;,&quot;description&quot;:&quot;You are the Don of Dons.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:2877,&quot;achieved_percent&quot;:0.00023198883292683547,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-pass-7.png&quot;,&quot;id&quot;:85,&quot;name&quot;:&quot;Dreamcatcher&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;fruits-skill-pass-7&quot;,&quot;description&quot;:&quot;No fruit, only dreams now.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:41347,&quot;achieved_percent&quot;:0.0028717073243573524,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-pass-7.png&quot;,&quot;id&quot;:93,&quot;name&quot;:&quot;Extra Credit&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;mania-skill-pass-7&quot;,&quot;description&quot;:&quot;See me after class.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:117384,&quot;achieved_percent&quot;:0.004115196185064773,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-pass-8.png&quot;,&quot;id&quot;:62,&quot;name&quot;:&quot;Absolution&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;osu-skill-pass-8&quot;,&quot;description&quot;:&quot;My god, you're full of stars!&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:5155,&quot;achieved_percent&quot;:0.00036691913977640497,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-pass-8.png&quot;,&quot;id&quot;:78,&quot;name&quot;:&quot;Rhythm Incarnate&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;taiko-skill-pass-8&quot;,&quot;description&quot;:&quot;Feel the beat. Become the beat.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1476,&quot;achieved_percent&quot;:0.00011901825422315229,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-pass-8.png&quot;,&quot;id&quot;:86,&quot;name&quot;:&quot;Lord of the Catch&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;fruits-skill-pass-8&quot;,&quot;description&quot;:&quot;Your kingdom kneels before you.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:18501,&quot;achieved_percent&quot;:0.0012849652262059007,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-pass-8.png&quot;,&quot;id&quot;:94,&quot;name&quot;:&quot;Maniac&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;mania-skill-pass-8&quot;,&quot;description&quot;:&quot;There's just no stopping you.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:45748,&quot;achieved_percent&quot;:0.0016038130841881622,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-pass-9.png&quot;,&quot;id&quot;:242,&quot;name&quot;:&quot;Event Horizon&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;osu-skill-pass-9&quot;,&quot;description&quot;:&quot;No force dares to pull you under.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Stare into the abyss, and pass the trial of any 9 star map.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:18996,&quot;achieved_percent&quot;:0.0006659533388834119,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-pass-10.png&quot;,&quot;id&quot;:244,&quot;name&quot;:&quot;Phantasm&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:4,&quot;slug&quot;:&quot;osu-skill-pass-10&quot;,&quot;description&quot;:&quot;Fevered is your passion, extraordinary is your skill.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Approach the limit of human endurance, and pass a 10 star map.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:5276333,&quot;achieved_percent&quot;:0.18497534104078384,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-fc-1.png&quot;,&quot;id&quot;:63,&quot;name&quot;:&quot;Totality&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;osu-skill-fc-1&quot;,&quot;description&quot;:&quot;All the notes. Every single one.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:708338,&quot;achieved_percent&quot;:0.05041760807583688,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-fc-1.png&quot;,&quot;id&quot;:95,&quot;name&quot;:&quot;Keeping Time&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;taiko-skill-fc-1&quot;,&quot;description&quot;:&quot;Don, then katsu. Don, then katsu..&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:520985,&quot;achieved_percent&quot;:0.042009976406808265,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-fc-1.png&quot;,&quot;id&quot;:103,&quot;name&quot;:&quot;Sweet And Sour&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;fruits-skill-fc-1&quot;,&quot;description&quot;:&quot;Apples and oranges, literally.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1497167,&quot;achieved_percent&quot;:0.10398397561337278,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-fc-1.png&quot;,&quot;id&quot;:111,&quot;name&quot;:&quot;Keystruck&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;mania-skill-fc-1&quot;,&quot;description&quot;:&quot;The beginning of a new story.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:4018020,&quot;achieved_percent&quot;:0.14086196223943603,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-fc-2.png&quot;,&quot;id&quot;:64,&quot;name&quot;:&quot;Business As Usual&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;osu-skill-fc-2&quot;,&quot;description&quot;:&quot;Two to go, please.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:230550,&quot;achieved_percent&quot;:0.016409933593685772,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-fc-2.png&quot;,&quot;id&quot;:96,&quot;name&quot;:&quot;To Your Own Beat&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;taiko-skill-fc-2&quot;,&quot;description&quot;:&quot;Straight and steady.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:72538,&quot;achieved_percent&quot;:0.005849150491083348,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-fc-2.png&quot;,&quot;id&quot;:104,&quot;name&quot;:&quot;Reaching The Core&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;fruits-skill-fc-2&quot;,&quot;description&quot;:&quot;The seeds of future success.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:656716,&quot;achieved_percent&quot;:0.04561143848943486,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-fc-2.png&quot;,&quot;id&quot;:112,&quot;name&quot;:&quot;Keying In&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;mania-skill-fc-2&quot;,&quot;description&quot;:&quot;Finding your groove.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1903908,&quot;achieved_percent&quot;:0.06674636184074748,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-fc-3.png&quot;,&quot;id&quot;:65,&quot;name&quot;:&quot;Building Steam&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;osu-skill-fc-3&quot;,&quot;description&quot;:&quot;Hey, this isn't so bad.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:69941,&quot;achieved_percent&quot;:0.004978213686731628,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-fc-3.png&quot;,&quot;id&quot;:97,&quot;name&quot;:&quot;Big Drums&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;taiko-skill-fc-3&quot;,&quot;description&quot;:&quot;Bigger scores to match.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:21627,&quot;achieved_percent&quot;:0.0017439077127941157,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-fc-3.png&quot;,&quot;id&quot;:105,&quot;name&quot;:&quot;Clean Platter&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;fruits-skill-fc-3&quot;,&quot;description&quot;:&quot;Clean only of failure. It is completely full, otherwise.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:318954,&quot;achieved_percent&quot;:0.022152575469395,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-fc-3.png&quot;,&quot;id&quot;:113,&quot;name&quot;:&quot;Hyperflow&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;mania-skill-fc-3&quot;,&quot;description&quot;:&quot;You can *feel* the rhythm.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1161530,&quot;achieved_percent&quot;:0.04072040333297797,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-fc-4.png&quot;,&quot;id&quot;:66,&quot;name&quot;:&quot;Moving Forward&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;osu-skill-fc-4&quot;,&quot;description&quot;:&quot;Bet you feel good about that.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:33287,&quot;achieved_percent&quot;:0.0023692798071265164,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-fc-4.png&quot;,&quot;id&quot;:98,&quot;name&quot;:&quot;Adversity Overcome&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;taiko-skill-fc-4&quot;,&quot;description&quot;:&quot;Difficult? Not for you.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:8540,&quot;achieved_percent&quot;:0.0006886286524835505,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-fc-4.png&quot;,&quot;id&quot;:106,&quot;name&quot;:&quot;Between The Rain&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;fruits-skill-fc-4&quot;,&quot;description&quot;:&quot;No umbrella needed.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:135728,&quot;achieved_percent&quot;:0.009426828832088778,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-fc-4.png&quot;,&quot;id&quot;:114,&quot;name&quot;:&quot;Breakthrough&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;mania-skill-fc-4&quot;,&quot;description&quot;:&quot;Many skills mastered, rolled into one.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:608689,&quot;achieved_percent&quot;:0.021339148867740847,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-fc-5.png&quot;,&quot;id&quot;:67,&quot;name&quot;:&quot;Paradigm Shift&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;osu-skill-fc-5&quot;,&quot;description&quot;:&quot;Surprisingly difficult.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:16865,&quot;achieved_percent&quot;:0.0012004056823140775,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-fc-5.png&quot;,&quot;id&quot;:99,&quot;name&quot;:&quot;Demonslayer&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;taiko-skill-fc-5&quot;,&quot;description&quot;:&quot;An Oni felled forevermore.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:4590,&quot;achieved_percent&quot;:0.00037011774179151016,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-fc-5.png&quot;,&quot;id&quot;:107,&quot;name&quot;:&quot;Addicted&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;fruits-skill-fc-5&quot;,&quot;description&quot;:&quot;That was an overdose?&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:43055,&quot;achieved_percent&quot;:0.0029903344583695505,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-fc-5.png&quot;,&quot;id&quot;:115,&quot;name&quot;:&quot;Everything Extra&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;mania-skill-fc-5&quot;,&quot;description&quot;:&quot;Giving your all is giving everything you have.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:213227,&quot;achieved_percent&quot;:0.007475217550541866,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-fc-6.png&quot;,&quot;id&quot;:68,&quot;name&quot;:&quot;Anguish Quelled&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;osu-skill-fc-6&quot;,&quot;description&quot;:&quot;Don't choke.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:7582,&quot;achieved_percent&quot;:0.0005396665213937347,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-fc-6.png&quot;,&quot;id&quot;:100,&quot;name&quot;:&quot;Rhythm's Call&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;taiko-skill-fc-6&quot;,&quot;description&quot;:&quot;Heralding true skill.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:2547,&quot;achieved_percent&quot;:0.00020537906064117134,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-fc-6.png&quot;,&quot;id&quot;:108,&quot;name&quot;:&quot;Quickening&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;fruits-skill-fc-6&quot;,&quot;description&quot;:&quot;A dash above normal limits.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:13575,&quot;achieved_percent&quot;:0.0009428356816250528,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-fc-6.png&quot;,&quot;id&quot;:116,&quot;name&quot;:&quot;Level Breaker&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;mania-skill-fc-6&quot;,&quot;description&quot;:&quot;Finesse beyond reason.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:48643,&quot;achieved_percent&quot;:0.0017053047095865344,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-fc-7.png&quot;,&quot;id&quot;:69,&quot;name&quot;:&quot;Never Give Up&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;osu-skill-fc-7&quot;,&quot;description&quot;:&quot;Excellence is its own reward.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:3823,&quot;achieved_percent&quot;:0.0002721109352793785,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-fc-7.png&quot;,&quot;id&quot;:101,&quot;name&quot;:&quot;Time Everlasting&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;taiko-skill-fc-7&quot;,&quot;description&quot;:&quot;Not a single beat escapes you.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1175,&quot;achieved_percent&quot;:9.474691647168289e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-fc-7.png&quot;,&quot;id&quot;:109,&quot;name&quot;:&quot;Supersonic&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;fruits-skill-fc-7&quot;,&quot;description&quot;:&quot;Faster than is reasonably necessary.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:2449,&quot;achieved_percent&quot;:0.00017009241873294691,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-fc-7.png&quot;,&quot;id&quot;:117,&quot;name&quot;:&quot;Step Up&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;mania-skill-fc-7&quot;,&quot;description&quot;:&quot;A precipice rarely seen.&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:7068,&quot;achieved_percent&quot;:0.0002477868077083573,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-fc-8.png&quot;,&quot;id&quot;:70,&quot;name&quot;:&quot;Aberration&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;osu-skill-fc-8&quot;,&quot;description&quot;:&quot;They said it couldn't be done. They were wrong.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:2880,&quot;achieved_percent&quot;:0.00020499071242600315,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/taiko-skill-fc-8.png&quot;,&quot;id&quot;:102,&quot;name&quot;:&quot;The Drummer's Throne&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;taiko-skill-fc-8&quot;,&quot;description&quot;:&quot;Percussive brilliance befitting royalty alone.&quot;,&quot;mode&quot;:&quot;taiko&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:477,&quot;achieved_percent&quot;:3.846321630382361e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/fruits-skill-fc-8.png&quot;,&quot;id&quot;:110,&quot;name&quot;:&quot;Dashing Scarlet&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;fruits-skill-fc-8&quot;,&quot;description&quot;:&quot;Speed beyond mortal reckoning.&quot;,&quot;mode&quot;:&quot;fruits&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:513,&quot;achieved_percent&quot;:3.5629812498979894e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/mania-skill-fc-8.png&quot;,&quot;id&quot;:118,&quot;name&quot;:&quot;Behind The Veil&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;mania-skill-fc-8&quot;,&quot;description&quot;:&quot;Supernatural!&quot;,&quot;mode&quot;:&quot;mania&quot;,&quot;instructions&quot;:null},{&quot;achieved_count&quot;:1178,&quot;achieved_percent&quot;:4.129780128472622e-5,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-fc-9.png&quot;,&quot;id&quot;:243,&quot;name&quot;:&quot;Chosen&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;osu-skill-fc-9&quot;,&quot;description&quot;:&quot;Reign among the Prometheans, where you belong.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Triumph over one of the hardest beatmaps ever made, and FC a 9 star map.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:256,&quot;achieved_percent&quot;:8.974734404830146e-6,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-fc-10.png&quot;,&quot;id&quot;:245,&quot;name&quot;:&quot;Unfathomable&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:5,&quot;slug&quot;:&quot;osu-skill-fc-10&quot;,&quot;description&quot;:&quot;You have no equal.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;i&gt;Cement your place among legends, and FC any 10 star map.&lt;\/i&gt;&quot;},{&quot;achieved_count&quot;:108183,&quot;achieved_percent&quot;:0.0037926316098349207,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-skill-dc-1.png&quot;,&quot;id&quot;:336,&quot;name&quot;:&quot;Daily Sprout&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;all-skill-dc-1&quot;,&quot;description&quot;:&quot;Ready for anything.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;Achieve a 1-day streak in Daily Challenge&quot;},{&quot;achieved_count&quot;:7551,&quot;achieved_percent&quot;:0.00026471960738622043,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-skill-dc-7.png&quot;,&quot;id&quot;:337,&quot;name&quot;:&quot;Weekly Sapling&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;all-skill-dc-7&quot;,&quot;description&quot;:&quot;Circadian rhythm calibrated.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;Achieve a 7-day streak in Daily Challenge&quot;},{&quot;achieved_count&quot;:3252,&quot;achieved_percent&quot;:0.00011400717298635795,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/all-skill-dc-30.png&quot;,&quot;id&quot;:338,&quot;name&quot;:&quot;Monthly Shrub&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:6,&quot;slug&quot;:&quot;all-skill-dc-30&quot;,&quot;description&quot;:&quot;In for the grind.&quot;,&quot;mode&quot;:null,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;Achieve a 1-month streak in Daily Challenge&quot;},{&quot;achieved_count&quot;:147972,&quot;achieved_percent&quot;:0.0051875367162168996,&quot;icon_url&quot;:&quot;https:\/\/assets.ppy.sh\/medals\/web\/osu-skill-cyclone.png&quot;,&quot;id&quot;:354,&quot;name&quot;:&quot;Cyclone&quot;,&quot;grouping&quot;:&quot;Skill &amp; Dedication&quot;,&quot;ordering&quot;:7,&quot;slug&quot;:&quot;osu-skill-cyclone&quot;,&quot;description&quot;:&quot;Clockwise or anticlockwise, that is the question.&quot;,&quot;mode&quot;:&quot;osu&quot;,&quot;instructions&quot;:&quot;&lt;b&gt;osu!(lazer) only&lt;\/b&gt;&lt;br&gt;&lt;i&gt;Reach 477 spins per minute on a spinner.&lt;\/i&gt;&quot;}],&quot;current_mode&quot;:&quot;osu&quot;,&quot;score_processing_notice_url&quot;:null,&quot;user&quot;:{&quot;avatar_url&quot;:&quot;https:\/\/a.ppy.sh\/2?1657169614.png&quot;,&quot;country_code&quot;:&quot;AU&quot;,&quot;default_group&quot;:&quot;default&quot;,&quot;id&quot;:2,&quot;is_active&quot;:true,&quot;is_bot&quot;:false,&quot;is_deleted&quot;:false,&quot;is_online&quot;:false,&quot;is_supporter&quot;:true,&quot;last_visit&quot;:&quot;2026-07-30T02:49:01+00:00&quot;,&quot;pm_friends_only&quot;:false,&quot;profile_colour&quot;:&quot;#3366FF&quot;,&quot;username&quot;:&quot;peppy&quot;,&quot;cover_url&quot;:&quot;https:\/\/assets.ppy.sh\/user-profile-covers\/2\/baba245ef60834b769694178f8f6d4f6166c5188c740de084656ad2b80f1eea7.jpeg&quot;,&quot;discord&quot;:null,&quot;has_supported&quot;:true,&quot;interests&quot;:null,&quot;join_date&quot;:&quot;2007-08-28T03:09:12+00:00&quot;,&quot;location&quot;:null,&quot;max_blocks&quot;:200,&quot;max_friends&quot;:1000,&quot;occupation&quot;:null,&quot;playmode&quot;:&quot;osu&quot;,&quot;playstyle&quot;:[&quot;mouse&quot;,&quot;touch&quot;],&quot;post_count&quot;:18226,&quot;profile_hue&quot;:252,&quot;profile_order&quot;:[&quot;me&quot;,&quot;recent_activity&quot;,&quot;beatmaps&quot;,&quot;historical&quot;,&quot;kudosu&quot;,&quot;top_ranks&quot;,&quot;medals&quot;],&quot;title&quot;:null,&quot;title_url&quot;:null,&quot;twitter&quot;:null,&quot;website&quot;:null,&quot;country&quot;:{&quot;code&quot;:&quot;AU&quot;,&quot;name&quot;:&quot;Australia&quot;},&quot;cover&quot;:{&quot;custom_url&quot;:&quot;https:\/\/assets.ppy.sh\/user-profile-covers\/2\/baba245ef60834b769694178f8f6d4f6166c5188c740de084656ad2b80f1eea7.jpeg&quot;,&quot;url&quot;:&quot;https:\/\/assets.ppy.sh\/user-profile-covers\/2\/baba245ef60834b769694178f8f6d4f6166c5188c740de084656ad2b80f1eea7.jpeg&quot;,&quot;id&quot;:null},&quot;is_admin&quot;:true,&quot;is_bng&quot;:false,&quot;is_full_bn&quot;:false,&quot;is_gmt&quot;:false,&quot;is_limited_bn&quot;:false,&quot;is_moderator&quot;:false,&quot;is_nat&quot;:false,&quot;is_restricted&quot;:false,&quot;is_silenced&quot;:false,&quot;kudosu&quot;:{&quot;available&quot;:62,&quot;total&quot;:88},&quot;account_history&quot;:[],&quot;active_tournament_banner&quot;:null,&quot;active_tournament_banners&quot;:[],&quot;badges&quot;:[],&quot;comments_count&quot;:2981,&quot;current_season_stats&quot;:null,&quot;current_user_attributes&quot;:null,&quot;daily_challenge_user_stats&quot;:{&quot;daily_streak_best&quot;:2,&quot;daily_streak_current&quot;:0,&quot;last_update&quot;:&quot;2025-09-04T00:00:00+00:00&quot;,&quot;last_weekly_streak&quot;:&quot;2025-09-04T00:00:00+00:00&quot;,&quot;playcount&quot;:4,&quot;top_10p_placements&quot;:0,&quot;top_50p_placements&quot;:0,&quot;user_id&quot;:2,&quot;weekly_streak_best&quot;:1,&quot;weekly_streak_current&quot;:0},&quot;follower_count&quot;:59754,&quot;groups&quot;:[{&quot;colour&quot;:&quot;#0066FF&quot;,&quot;has_listing&quot;:false,&quot;has_playmodes&quot;:false,&quot;id&quot;:33,&quot;identifier&quot;:&quot;ppy&quot;,&quot;is_probationary&quot;:false,&quot;name&quot;:&quot;ppy&quot;,&quot;short_name&quot;:&quot;PPY&quot;,&quot;playmodes&quot;:null},{&quot;colour&quot;:&quot;#E45678&quot;,&quot;has_listing&quot;:true,&quot;has_playmodes&quot;:false,&quot;id&quot;:11,&quot;identifier&quot;:&quot;dev&quot;,&quot;is_probationary&quot;:false,&quot;name&quot;:&quot;Developers&quot;,&quot;short_name&quot;:&quot;DEV&quot;,&quot;playmodes&quot;:null}],&quot;mapping_follower_count&quot;:2326,&quot;matchmaking_stats&quot;:[{&quot;first_placements&quot;:0,&quot;is_rating_provisional&quot;:true,&quot;plays&quot;:4,&quot;pool_id&quot;:38,&quot;rank&quot;:114205,&quot;rank_percent&quot;:0.9419901351061548,&quot;rating&quot;:907,&quot;total_points&quot;:0,&quot;user_id&quot;:2,&quot;pool&quot;:{&quot;active&quot;:true,&quot;id&quot;:38,&quot;name&quot;:&quot;RP: Season 0&quot;,&quot;ruleset_id&quot;:0,&quot;type&quot;:&quot;ranked_play&quot;,&quot;variant_id&quot;:0}}],&quot;page&quot;:{&quot;html&quot;:&quot;&lt;div class='bbcode bbcode--profile-page'&gt;&lt;div class=\&quot;bbcode__align-centre\&quot;&gt;&lt;span style=\&quot;font-size:85%;\&quot;&gt;(&lt;span style=\&quot;color:#f462a3;\&quot;&gt;\u0e51&lt;\/span&gt;\u30fb\u03c9\u30fb&lt;span style=\&quot;color:#f462a3;\&quot;&gt;\u0e51&lt;\/span&gt;)&lt;\/span&gt;&lt;br \/&gt;&lt;br \/&gt;(&lt;span style=\&quot;color:#f462a3;\&quot;&gt;\u0e51&lt;\/span&gt;\u30fb\u03c9\u30fb&lt;span style=\&quot;color:#f462a3;\&quot;&gt;\u0e51&lt;\/span&gt;)&lt;br \/&gt;&lt;br \/&gt;&lt;span style=\&quot;font-size:150%;\&quot;&gt;(&lt;span style=\&quot;color:#f462a3;\&quot;&gt;\u0e51&lt;\/span&gt;\u30fb\u03c9\u30fb&lt;span style=\&quot;color:#f462a3;\&quot;&gt;\u0e51&lt;\/span&gt;)&lt;\/span&gt;&lt;br \/&gt;&lt;br \/&gt;&lt;\/div&gt;&lt;br \/&gt;&lt;div class=\&quot;bbcode__align-centre\&quot;&gt;&lt;span style=\&quot;font-size:85%;\&quot;&gt;&lt;a rel=\&quot;nofollow\&quot; href=\&quot;http:\/\/blog.ppy.sh\/\&quot;&gt;dev blog&lt;\/a&gt; | &lt;a rel=\&quot;nofollow\&quot; href=\&quot;http:\/\/osu.ppy.sh\/p\/changelog\&quot;&gt;changelog&lt;\/a&gt; | &lt;a rel=\&quot;nofollow\&quot; href=\&quot;http:\/\/osu.ppy.sh\/community\/forums\/topics\/83155\&quot;&gt;make osu! more awesome!&lt;\/a&gt; | &lt;a rel=\&quot;nofollow\&quot; href=\&quot;http:\/\/osustream.com\&quot;&gt;osu!stream (iOS)&lt;\/a&gt;&lt;\/span&gt;&lt;\/div&gt;&lt;\/div&gt;&quot;,&quot;raw&quot;:&quot;[centre]\n[size=85]([color=#f462a3]\u0e51[\/color]\u30fb\u03c9\u30fb[color=#f462a3]\u0e51[\/color])[\/size]\n\n([color=#f462a3]\u0e51[\/color]\u30fb\u03c9\u30fb[color=#f462a3]\u0e51[\/color])\n\n[size=150]([color=#f462a3]\u0e51[\/color]\u30fb\u03c9\u30fb[color=#f462a3]\u0e51[\/color])[\/size]\n\n[\/centre]\n\n[centre][size=85][url=http:\/\/blog.ppy.sh\/]dev blog[\/url] | [url=http:\/\/osu.ppy.sh\/p\/changelog]changelog[\/url] | [url=http:\/\/osu.ppy.sh\/community\/forums\/topics\/83155]make osu! more awesome![\/url] | [url=http:\/\/osustream.com]osu!stream (iOS)[\/url][\/size][\/centre]&quot;},&quot;pending_beatmapset_count&quot;:0,&quot;previous_usernames&quot;:[],&quot;rank_highest&quot;:{&quot;rank&quot;:243738,&quot;updated_at&quot;:&quot;2017-07-07T00:00:00Z&quot;},&quot;statistics&quot;:{&quot;count_100&quot;:124580,&quot;count_300&quot;:687750,&quot;count_50&quot;:27541,&quot;count_miss&quot;:76267,&quot;level&quot;:{&quot;current&quot;:67,&quot;progress&quot;:53},&quot;global_rank&quot;:743508,&quot;global_rank_percent&quot;:0.27740123913259224,&quot;global_rank_exp&quot;:null,&quot;pp&quot;:1175.66,&quot;pp_exp&quot;:0,&quot;ranked_score&quot;:466015627,&quot;hit_accuracy&quot;:96.8413,&quot;accuracy&quot;:0.9684130000000001,&quot;play_count&quot;:7769,&quot;play_time&quot;:744884,&quot;total_score&quot;:2030915816,&quot;total_hits&quot;:839871,&quot;maximum_combo&quot;:746,&quot;replays_watched_by_others&quot;:16733,&quot;is_ranked&quot;:true,&quot;grade_counts&quot;:{&quot;ss&quot;:15,&quot;ssh&quot;:0,&quot;s&quot;:67,&quot;sh&quot;:0,&quot;a&quot;:179},&quot;country_rank&quot;:15188,&quot;rank&quot;:{&quot;country&quot;:15188}},&quot;support_level&quot;:3,&quot;team&quot;:{&quot;flag_url&quot;:&quot;https:\/\/assets.ppy.sh\/teams\/flag\/1\/b46fb10dbfd8a35dc50e6c00296c0dc6172dffc3ed3d3a4b379277ba498399fe.png&quot;,&quot;id&quot;:1,&quot;name&quot;:&quot;mom?&quot;,&quot;short_name&quot;:&quot;MOM&quot;},&quot;user_achievements&quot;:[{&quot;achieved_at&quot;:&quot;2026-04-21T05:26:22Z&quot;,&quot;achievement_id&quot;:356},{&quot;achieved_at&quot;:&quot;2026-04-17T04:44:02Z&quot;,&quot;achievement_id&quot;:38},{&quot;achieved_at&quot;:&quot;2025-09-04T07:52:29Z&quot;,&quot;achievement_id&quot;:336},{&quot;achieved_at&quot;:&quot;2024-09-06T11:57:49Z&quot;,&quot;achievement_id&quot;:328},{&quot;achieved_at&quot;:&quot;2024-08-29T00:32:43Z&quot;,&quot;achievement_id&quot;:95},{&quot;achieved_at&quot;:&quot;2024-08-29T00:32:43Z&quot;,&quot;achievement_id&quot;:31},{&quot;achieved_at&quot;:&quot;2019-10-24T09:16:47Z&quot;,&quot;achievement_id&quot;:177},{&quot;achieved_at&quot;:&quot;2019-10-24T09:07:16Z&quot;,&quot;achievement_id&quot;:124},{&quot;achieved_at&quot;:&quot;2019-07-29T02:40:32Z&quot;,&quot;achievement_id&quot;:79},{&quot;achieved_at&quot;:&quot;2018-12-19T07:33:32Z&quot;,&quot;achievement_id&quot;:71},{&quot;achieved_at&quot;:&quot;2018-12-19T07:23:27Z&quot;,&quot;achievement_id&quot;:63},{&quot;achieved_at&quot;:&quot;2017-10-28T00:56:59Z&quot;,&quot;achievement_id&quot;:55},{&quot;achieved_at&quot;:&quot;2017-01-23T09:35:35Z&quot;,&quot;achievement_id&quot;:72},{&quot;achieved_at&quot;:&quot;2017-01-14T05:12:27Z&quot;,&quot;achievement_id&quot;:128},{&quot;achieved_at&quot;:&quot;2016-10-17T06:04:28Z&quot;,&quot;achievement_id&quot;:42},{&quot;achieved_at&quot;:&quot;2016-09-26T15:08:31Z&quot;,&quot;achievement_id&quot;:64},{&quot;achieved_at&quot;:&quot;2016-09-26T15:08:31Z&quot;,&quot;achievement_id&quot;:56},{&quot;achieved_at&quot;:&quot;2016-09-26T14:35:17Z&quot;,&quot;achievement_id&quot;:127},{&quot;achieved_at&quot;:&quot;2016-09-26T14:23:04Z&quot;,&quot;achievement_id&quot;:132},{&quot;achieved_at&quot;:&quot;2016-09-26T14:23:04Z&quot;,&quot;achievement_id&quot;:58},{&quot;achieved_at&quot;:&quot;2016-05-05T11:24:22Z&quot;,&quot;achievement_id&quot;:57},{&quot;achieved_at&quot;:&quot;2016-04-20T05:47:10Z&quot;,&quot;achievement_id&quot;:54},{&quot;achieved_at&quot;:&quot;2013-02-27T12:31:07Z&quot;,&quot;achievement_id&quot;:1},{&quot;achieved_at&quot;:&quot;2013-02-27T12:15:27Z&quot;,&quot;achievement_id&quot;:39},{&quot;achieved_at&quot;:&quot;2012-10-28T14:57:49Z&quot;,&quot;achievement_id&quot;:20}],&quot;rank_history&quot;:{&quot;mode&quot;:&quot;osu&quot;,&quot;data&quot;:[798693,799112,799600,800129,800554,800938,801359,801770,802220,802694,803243,803755,804167,804438,804747,805128,805548,806061,806541,807021,807491,807914,808376,808817,809309,809820,810384,810867,811323,811785,812266,812790,813288,813765,814178,814669,815110,815583,816105,816603,817068,817555,818012,818468,818969,819543,820082,820625,821139,821668,822193,822725,823298,823792,824331,824865,825352,825851,826344,826876,827382,827900,828379,828872,829418,829925,830493,831027,831582,730468,731231,732160,733003,733880,734664,735505,736314,737100,737798,738479,739094,739504,739713,740290,740944,741621,742328,742898,743508,743508]},&quot;rankHistory&quot;:{&quot;mode&quot;:&quot;osu&quot;,&quot;data&quot;:[798693,799112,799600,800129,800554,800938,801359,801770,802220,802694,803243,803755,804167,804438,804747,805128,805548,806061,806541,807021,807491,807914,808376,808817,809309,809820,810384,810867,811323,811785,812266,812790,813288,813765,814178,814669,815110,815583,816105,816603,817068,817555,818012,818468,818969,819543,820082,820625,821139,821668,822193,822725,823298,823792,824331,824865,825352,825851,826344,826876,827382,827900,828379,828872,829418,829925,830493,831027,831582,730468,731231,732160,733003,733880,734664,735505,736314,737100,737798,738479,739094,739504,739713,740290,740944,741621,742328,742898,743508,743508]},&quot;unranked_beatmapset_count&quot;:0},&quot;user_cover_presets&quot;:[]}" data-react="profile-page"><div><div class="osu-layout osu-layout--full"><div class="header-v4 header-v4--users"><div class="header-v4__container header-v4__container--main"><div class="header-v4__bg-container"><div class="header-v4__bg undefined" style="background-image: url(&quot;https://assets.ppy.sh/user-profile-covers/2/baba245ef60834b769694178f8f6d4f6166c5188c740de084656ad2b80f1eea7.jpeg&quot;);"></div></div><div class="hidden-xs js-sync-height--target" data-sync-height-id="notification-banners" style="min-height: 0px;"></div><div class="header-v4__content"><div class="header-v4__row header-v4__row--title"><div class="header-v4__icon"></div><div class="header-v4__title">player info</div></div></div></div><div class="header-v4__container"><div class="header-v4__content"><div class="header-v4__row header-v4__row--bar"><ul class="header-nav-v4 header-nav-v4--list"><li class="header-nav-v4__item"><a class="header-nav-v4__link header-nav-v4__link--active" href="https://osu.ppy.sh/users/2"><span class="fake-bold" data-content="info">info</span></a></li><li class="header-nav-v4__item"><a class="header-nav-v4__link" href="https://osu.ppy.sh/users/2/modding"><span class="fake-bold" data-content="modding">modding</span></a></li><li class="header-nav-v4__item"><a class="header-nav-v4__link" href="https://osu.ppy.sh/users/2/playlists"><span class="fake-bold" data-content="playlists">playlists</span></a></li><li class="header-nav-v4__item"><a class="header-nav-v4__link" href="https://osu.ppy.sh/users/2/realtime"><span class="fake-bold" data-content="multiplayer">multiplayer</span></a></li><li class="header-nav-v4__item"><a class="header-nav-v4__link" href="https://osu.ppy.sh/users/2/ranked-play"><span class="fake-bold" data-content="ranked play">ranked play</span></a></li></ul><div class="header-nav-mobile"><a class="header-nav-mobile__toggle js-click-menu" data-click-menu-target="header-nav-mobile" href="https://osu.ppy.sh/users/2">info<span class="header-nav-mobile__toggle-icon"><span class="fas fa-chevron-down"></span></span></a><ul class="header-nav-mobile__menu js-click-menu" data-click-menu-id="header-nav-mobile" data-visibility="hidden"><li><a class="header-nav-mobile__item js-click-menu--close" href="https://osu.ppy.sh/users/2">info </a></li><li><a class="header-nav-mobile__item js-click-menu--close" href="https://osu.ppy.sh/users/2/modding">modding </a></li><li><a class="header-nav-mobile__item js-click-menu--close" href="https://osu.ppy.sh/users/2/playlists">playlists </a></li><li><a class="header-nav-mobile__item js-click-menu--close" href="https://osu.ppy.sh/users/2/realtime">multiplayer </a></li><li><a class="header-nav-mobile__item js-click-menu--close" href="https://osu.ppy.sh/users/2/ranked-play">ranked play </a></li></ul></div><ul class="game-mode"><li><a class="game-mode-link game-mode-link--active" data-mode="osu" href="https://osu.ppy.sh/users/2/osu"><span class="fal fa-extra-mode-osu" title="osu!"></span><span class="game-mode-link__icon" title="default game mode"><span class="fas fa-star"></span></span></a></li><li><a class="game-mode-link" data-mode="taiko" href="https://osu.ppy.sh/users/2/taiko"><span class="fal fa-extra-mode-taiko" title="osu!taiko"></span></a></li><li><a class="game-mode-link" data-mode="fruits" href="https://osu.ppy.sh/users/2/fruits"><span class="fal fa-extra-mode-fruits" title="osu!catch"></span></a></li><li><a class="game-mode-link" data-mode="mania" href="https://osu.ppy.sh/users/2/mania"><span class="fal fa-extra-mode-mania" title="osu!mania"></span></a></li></ul></div></div></div></div><div class="osu-page osu-page--generic-compact"><div data-page-id="main"><div class="profile-info profile-info--cover"><div class="profile-info__bg" style="background-image: url(&quot;https://assets.ppy.sh/user-profile-covers/2/baba245ef60834b769694178f8f6d4f6166c5188c740de084656ad2b80f1eea7.jpeg&quot;);"></div><div class="profile-info__details"><div class="profile-info__avatar"><span class="avatar avatar--guest avatar--full" style="background-image: url(&quot;https://a.ppy.sh/2?1657169614.png&quot;);"></span></div><div class="profile-info__info"><h1 class="profile-info__name"><span class="u-ellipsis-pre-overflow">peppy</span><div class="profile-info__previous-usernames"></div><div class="profile-info__icons profile-info__icons--name-inline"><a class="profile-info__icon profile-info__icon--supporter" href="https://osu.ppy.sh/home/support" title="osu!supporter"><span class="fas fa-heart"></span><span class="fas fa-heart"></span><span class="fas fa-heart"></span></a><span class="profile-info__icon"><div class="user-group-badge user-group-badge--ppy user-group-badge--profile-page" data-label="PPY" style="--group-colour: #0066FF;" title="ppy"></div></span><span class="profile-info__icon"><a class="user-group-badge user-group-badge--dev user-group-badge--profile-page" data-label="DEV" style="--group-colour: #E45678;" title="Developers" href="https://osu.ppy.sh/groups/11"></a></span></div></h1><div class="profile-info__flags"><a class="profile-info__flag" href="https://osu.ppy.sh/rankings/osu/performance?country=AU"><span class="flag-country" style="background-image: url(&quot;/assets/images/flags/1f1e6-1f1fa.svg&quot;);" title="Australia" original-title="Australia"></span><span class="profile-info__flag-text">Australia</span></a><a class="profile-info__flag" href="https://osu.ppy.sh/teams/1"><span class="flag-team" style="background-image: url(&quot;https://assets.ppy.sh/teams/flag/1/b46fb10dbfd8a35dc50e6c00296c0dc6172dffc3ed3d3a4b379277ba498399fe.png&quot;);" title="mom?"></span><span class="profile-info__flag-text u-ellipsis-overflow">mom?</span></a><div class="profile-info__icons profile-info__icons--flag-inline"><a class="profile-info__icon profile-info__icon--supporter" href="https://osu.ppy.sh/home/support" title="osu!supporter"><span class="fas fa-heart"></span><span class="fas fa-heart"></span><span class="fas fa-heart"></span></a><span class="profile-info__icon"><div class="user-group-badge user-group-badge--ppy user-group-badge--profile-page" data-label="PPY" style="--group-colour: #0066FF;" title="ppy"></div></span><span class="profile-info__icon"><a class="user-group-badge user-group-badge--dev user-group-badge--profile-page" data-label="DEV" style="--group-colour: #E45678;" title="Developers" href="https://osu.ppy.sh/groups/11"></a></span></div></div></div><div class="profile-info__cover-toggle"><button class="btn-circle btn-circle--page-toggle" title="Hide cover" type="button"><span class="fas fa-chevron-up"></span></button></div></div></div><div class="profile-detail"><div class="profile-detail-stats"><div><div class="profile-detail-stats__chart-numbers profile-detail-stats__chart-numbers--top"><div class="profile-detail-stats__values"><div class="value-display value-display--rank"><div class="value-display__label u-ellipsis-overflow">Global Ranking</div><div class="value-display__value u-ellipsis-overflow"><div class="rank-value rank-value--iron" data-html-title="&lt;div&gt;Highest rank: #243,738 on 7 Jul 2017&lt;/div&gt;" data-tooltip-position="bottom left" style="--colour: var(--level-tier-iron);" data-orig-title="" data-hasqtip="0">#743,508</div></div></div><div class="value-display value-display--rank"><div class="value-display__label u-ellipsis-overflow">Country Ranking</div><div class="value-display__value u-ellipsis-overflow"><div class="rank-value rank-value--base" data-html-title="" data-tooltip-position="bottom left" title="">#15,188</div></div></div><div class="respektiveScore value-display value-display--rank"><div class="value-display__label">Score Ranking</div><div class="value-display__value"><div data-html-title="&lt;div&gt;Highest rank: #3 on 11 October 2007&lt;/div&gt;" title="">-</div></div></div></div><div class="profile-detail-stats__values"><div class="daily-challenge"><div class="daily-challenge__name">Ranked Play</div><div class="daily-challenge__value-box"><div class="daily-challenge__value daily-challenge__value--plain"><span class="u-fancy-text" style="--colour: var(--level-tier-silver);">#114,205</span></div></div></div><div class="daily-challenge"><div class="daily-challenge__name"><div>Daily</div><div>Challenge</div></div><div class="daily-challenge__value-box"><div class="daily-challenge__value" style="--colour: var(--level-tier-iron);">4d</div></div></div></div></div><div class="profile-detail-stats__chart"><div class="line-chart line-chart--profile-page"><svg width="599.3333129882812" height="90"><g class="line-chart__wrapper" transform="translate(0, 15)"><path class="line-chart__line" d="M0,41.324C2.245,41.402,4.489,41.48,6.734,41.567C8.979,41.655,11.223,41.752,13.468,41.85C15.713,41.948,17.958,42.064,20.202,42.156C22.447,42.248,24.692,42.323,26.936,42.401C29.181,42.479,31.426,42.546,33.67,42.623C35.915,42.701,38.16,42.787,40.404,42.867C42.649,42.947,44.894,43.021,47.139,43.104C49.383,43.187,51.628,43.275,53.873,43.364C56.117,43.452,58.362,43.539,60.607,43.637C62.851,43.735,65.096,43.851,67.341,43.953C69.586,44.055,71.83,44.16,74.075,44.248C76.32,44.337,78.564,44.42,80.809,44.485C83.054,44.551,85.298,44.586,87.543,44.641C89.788,44.697,92.032,44.753,94.277,44.819C96.522,44.885,98.767,44.961,101.011,45.038C103.256,45.115,105.501,45.19,107.745,45.28C109.99,45.369,112.235,45.479,114.479,45.574C116.724,45.669,118.969,45.758,121.213,45.85C123.458,45.941,125.703,46.034,127.948,46.125C130.192,46.216,132.437,46.309,134.682,46.394C136.926,46.48,139.171,46.552,141.416,46.637C143.66,46.721,145.905,46.815,148.15,46.901C150.395,46.988,152.639,47.065,154.884,47.154C157.129,47.243,159.373,47.34,161.618,47.435C163.863,47.531,166.107,47.625,168.352,47.727C170.597,47.83,172.841,47.95,175.086,48.05C177.331,48.149,179.576,48.236,181.82,48.325C184.065,48.415,186.31,48.498,188.554,48.586C190.799,48.673,193.044,48.759,195.288,48.849C197.533,48.939,199.778,49.028,202.022,49.123C204.267,49.219,206.512,49.325,208.757,49.422C211.001,49.519,213.246,49.613,215.491,49.705C217.735,49.798,219.98,49.892,222.225,49.976C224.469,50.061,226.714,50.126,228.959,50.211C231.203,50.297,233.448,50.402,235.693,50.49C237.938,50.579,240.182,50.654,242.427,50.741C244.672,50.827,246.916,50.915,249.161,51.009C251.406,51.103,253.65,51.209,255.895,51.305C258.14,51.402,260.385,51.497,262.629,51.588C264.874,51.679,267.119,51.761,269.363,51.851C271.608,51.941,273.853,52.038,276.097,52.127C278.342,52.216,280.587,52.299,282.831,52.386C285.076,52.472,287.321,52.553,289.566,52.643C291.81,52.734,294.055,52.825,296.3,52.927C298.544,53.028,300.789,53.146,303.034,53.251C305.278,53.356,307.523,53.453,309.768,53.555C312.012,53.657,314.257,53.762,316.502,53.862C318.747,53.961,320.991,54.053,323.236,54.151C325.481,54.249,327.725,54.35,329.97,54.449C332.215,54.548,334.459,54.646,336.704,54.745C338.949,54.844,341.193,54.941,343.438,55.044C345.683,55.148,347.928,55.267,350.172,55.367C352.417,55.467,354.662,55.547,356.906,55.644C359.151,55.741,361.396,55.846,363.64,55.947C365.885,56.047,368.13,56.151,370.375,56.247C372.619,56.342,374.864,56.428,377.109,56.52C379.353,56.612,381.598,56.707,383.843,56.799C386.087,56.892,388.332,56.98,390.577,57.076C392.821,57.171,395.066,57.277,397.311,57.374C399.556,57.47,401.8,57.561,404.045,57.657C406.29,57.752,408.534,57.853,410.779,57.946C413.024,58.039,415.268,58.123,417.513,58.214C419.758,58.304,422.002,58.393,424.247,58.489C426.492,58.586,428.737,58.696,430.981,58.794C433.226,58.892,435.471,58.977,437.715,59.077C439.96,59.177,442.205,59.291,444.449,59.394C446.694,59.496,448.939,59.59,451.184,59.691C453.428,59.792,455.673,60,457.918,60C460.162,60,462.407,0,464.652,0C466.896,0,469.141,0.305,471.386,0.483C473.63,0.662,475.875,0.884,478.12,1.071C480.365,1.257,482.609,1.422,484.854,1.603C487.099,1.784,489.343,1.982,491.588,2.157C493.833,2.331,496.077,2.48,498.322,2.651C500.567,2.821,502.811,3.007,505.056,3.18C507.301,3.353,509.546,3.522,511.79,3.689C514.035,3.856,516.28,4.028,518.524,4.183C520.769,4.338,523.014,4.477,525.258,4.621C527.503,4.765,529.748,4.913,531.992,5.048C534.237,5.183,536.482,5.326,538.727,5.433C540.971,5.54,543.216,5.625,545.461,5.69C547.705,5.754,549.95,5.739,552.195,5.821C554.439,5.903,556.684,6.053,558.929,6.181C561.174,6.31,563.418,6.452,565.663,6.59C567.908,6.729,570.152,6.869,572.397,7.013C574.642,7.157,576.886,7.321,579.131,7.454C581.376,7.587,583.62,7.687,585.865,7.809C588.11,7.932,590.355,8.189,592.599,8.189C594.844,8.189,597.089,8.189,599.333,8.189"></path></g></svg><div class="line-chart__hover-area" style="inset: 15px 0px;"><div class="line-chart__hover" data-visibility="hidden"><div class="line-chart__hover-line" style=""></div><div class="line-chart__hover-circle" style=""></div><div class="line-chart__hover-info-box" data-float="right"><div class="line-chart__hover-info-box-text line-chart__hover-info-box-text--x">85 days ago</div><div class="line-chart__hover-info-box-text line-chart__hover-info-box-text--y"><strong>Global Ranking</strong> #800,554</div></div></div></div></div></div><div class="profile-detail-stats__chart-numbers"><div class="profile-detail-stats__values profile-detail-stats__values--grid"><div class="value-display value-display--plain"><div class="value-display__label u-ellipsis-overflow">Medals</div><div class="value-display__value u-ellipsis-overflow">25</div></div><div class="value-display value-display--plain"><div class="value-display__label u-ellipsis-overflow">pp</div><div class="value-display__value u-ellipsis-overflow"><div data-html-title="">1,176</div></div></div><div class="value-display value-display--plain value-display--plain-wide"><div class="value-display__label u-ellipsis-overflow">Total Play Time</div><div class="value-display__value u-ellipsis-overflow"><span data-tooltip-position="bottom center" title="207 hours">8d 14h 54m</span></div></div></div><div class="profile-detail-stats__values"><div class="profile-rank-count"><div class="profile-rank-count__item"><div class="profile-rank-count__rank"><div class="score-rank score-rank--rank-ssh"></div></div>0</div><div class="profile-rank-count__item"><div class="profile-rank-count__rank"><div class="score-rank score-rank--rank-ss"></div></div>15</div><div class="profile-rank-count__item"><div class="profile-rank-count__rank"><div class="score-rank score-rank--rank-sh"></div></div>0</div><div class="profile-rank-count__item"><div class="profile-rank-count__rank"><div class="score-rank score-rank--rank-s"></div></div>67</div><div class="profile-rank-count__item"><div class="profile-rank-count__rank"><div class="score-rank score-rank--rank-a"></div></div>179</div></div></div></div></div><div class="profile-detail-stats__separator"></div><div class="profile-stats"><dl class="profile-stats__entry profile-stats__entry--key-ranked_score"><dt class="profile-stats__key">Ranked Score</dt><dd class="profile-stats__value">466,015,627</dd></dl><dl class="profile-stats__entry profile-stats__entry--key-hit_accuracy"><dt class="profile-stats__key">Hit Accuracy</dt><dd class="profile-stats__value">96.84%</dd></dl><dl class="profile-stats__entry profile-stats__entry--key-play_count"><dt class="profile-stats__key">Play Count</dt><dd class="profile-stats__value">7,769</dd></dl><dl class="profile-stats__entry profile-stats__entry--key-total_score"><dt class="profile-stats__key">Total Score</dt><dd class="profile-stats__value">2,030,915,816</dd></dl><dl class="profile-stats__entry profile-stats__entry--key-total_hits"><dt class="profile-stats__key">Total Hits</dt><dd class="profile-stats__value">839,871</dd></dl><dl class="profile-stats__entry profile-stats__entry--key-hits_per_play"><dt class="profile-stats__key">Hits Per Play</dt><dd class="profile-stats__value">108</dd></dl><dl class="profile-stats__entry profile-stats__entry--key-maximum_combo"><dt class="profile-stats__key">Maximum Combo</dt><dd class="profile-stats__value">746</dd></dl><dl class="profile-stats__entry profile-stats__entry--key-replays_watched_by_others"><dt class="profile-stats__key">Replays Watched by Others</dt><dd class="profile-stats__value">16,733</dd></dl></div></div></div><div class="profile-detail-bar"><div data-orig-title="followers" data-hasqtip="1" aria-describedby="qtip-1"><button class="user-action-button user-action-button--profile-page" disabled="" type="button"><span class="user-action-button__icon-container"><span class="fas fa-user"></span></span><span class="user-action-button__counter">59,754</span></button></div><div data-orig-title="mapping subscribers" data-hasqtip="3"><button class="user-action-button user-action-button--profile-page" disabled=""><span class="user-action-button__icon-container"><i class="fas fa-bell"></i></span><span class="user-action-button__counter">2,326</span></button></div><div><a class="user-action-button user-action-button--profile-page" href="https://osu.ppy.sh/home/messages/users/2" title="Send message"><i class="fas fa-envelope"></i></a></div><div class="profile-detail-bar__level"><div class="profile-detail-bar__level-bar"><div class="bar bar--user-profile" style="--fill: 53%;" title="progress to next level"><div class="bar__fill"></div><div class="bar__text">53%</div></div></div><div class="user-level" style="--bg: var(--level-tier-gold);" title="Level 67"><div class="user-level__icon"></div><span class="user-level__level">67</span></div></div></div><div class="profile-links"><div class="profile-links__row profile-links__row--0"><div class="profile-links__item"><span class="js-tooltip-time" data-orig-title="2007-08-28T03:09:12.000Z" data-hasqtip="2">Here since the beginning</span></div><div class="profile-links__item">Last seen <span class="profile-links__value"><time class="js-timeago" datetime="2026-07-30T02:49:01+00:00" title="2026-07-30T02:49:01+00:00">8 hours ago</time></span></div><div class="profile-links__item">Plays with <span class="profile-links__value">Mouse, Touch Screen</span></div><div class="profile-links__item">Contributed <a class="profile-links__value profile-links__value--link" href="https://osu.ppy.sh/users/2/posts">18,226 forum posts</a></div><div class="profile-links__item">Posted <a class="profile-links__value profile-links__value--link" href="https://osu.ppy.sh/comments?user_id=2">2,981 comments</a></div></div></div></div><div class="sticky-toolbar"><div class="page-mode page-mode--profile-page-extra u-hidden-desktop"><a class="page-mode__item " data-page-id="me" href="#me"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="me!">me!</span></span></a><a class="page-mode__item " data-page-id="recent_activity" href="#recent_activity"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="Recent">Recent</span></span></a><a class="page-mode__item " data-page-id="beatmaps" href="#beatmaps"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="Beatmaps">Beatmaps</span></span></a><a class="page-mode__item " data-page-id="historical" href="#historical"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="Historical">Historical</span></span></a><a class="page-mode__item " data-page-id="kudosu" href="#kudosu"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="Kudosu!">Kudosu!</span></span></a><a class="page-mode__item " data-page-id="top_ranks" href="#top_ranks"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="Scores">Scores</span></span></a><a class="page-mode__item " data-page-id="medals" href="#medals"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="Medals">Medals</span></span></a></div><div class="page-mode page-mode--profile-page-extra hidden-xs ui-sortable ui-sortable-disabled"><a class="page-mode__item js-sortable--tab ui-sortable-handle" data-page-id="me" href="#me"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="me!">me!</span></span></a><a class="page-mode__item js-sortable--tab ui-sortable-handle" data-page-id="recent_activity" href="#recent_activity"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="Recent">Recent</span></span></a><a class="page-mode__item js-sortable--tab ui-sortable-handle" data-page-id="beatmaps" href="#beatmaps"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="Beatmaps">Beatmaps</span></span></a><a class="page-mode__item js-sortable--tab ui-sortable-handle" data-page-id="historical" href="#historical"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="Historical">Historical</span></span></a><a class="page-mode__item js-sortable--tab ui-sortable-handle" data-page-id="kudosu" href="#kudosu"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="Kudosu!">Kudosu!</span></span></a><a class="page-mode__item js-sortable--tab ui-sortable-handle" data-page-id="top_ranks" href="#top_ranks"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="Scores">Scores</span></span></a><a class="page-mode__item js-sortable--tab ui-sortable-handle" data-page-id="medals" href="#medals"><span class="page-mode-link page-mode-link--profile-page"><span class="fake-bold" data-content="Medals">Medals</span></span></a></div></div><div class="user-profile-pages ui-sortable"><div class="js-sortable--page" data-page-id="me"><div class="page-extra page-extra--userpage"><div class="u-relative"><h2 class="title title--page-extra">me!</h2></div><div class="page-extra__content-overflow-wrapper-outer u-fancy-scrollbar"><div class="page-extra__content-overflow-wrapper-inner"><div class="js-audio--group"><div class="bbcode bbcode--profile-page"><div class="bbcode__align-centre"><span style="font-size:85%;">(<span style="color:#f462a3;">๑</span>・ω・<span style="color:#f462a3;">๑</span>)</span><br><br>(<span style="color:#f462a3;">๑</span>・ω・<span style="color:#f462a3;">๑</span>)<br><br><span style="font-size:150%;">(<span style="color:#f462a3;">๑</span>・ω・<span style="color:#f462a3;">๑</span>)</span><br><br></div><br><div class="bbcode__align-centre"><span style="font-size:85%;"><a rel="nofollow" href="http://blog.ppy.sh/">dev blog</a> | <a rel="nofollow" href="http://osu.ppy.sh/p/changelog">changelog</a> | <a rel="nofollow" href="http://osu.ppy.sh/community/forums/topics/83155">make osu! more awesome!</a> | <a rel="nofollow" href="http://osustream.com">osu!stream (iOS)</a></span></div></div></div></div></div></div></div><div class="js-sortable--page" data-page-id="recent_activity"><div class="page-extra"><div class="u-relative"><h2 class="title title--page-extra">Recent</h2></div><div class="lazy-load"><ul class="profile-extra-entries"><li class="profile-extra-entries__item"><div class="profile-extra-entries__detail"><div class="profile-extra-entries__icon profile-extra-entries__icon--pink"><span class="fas fa-gift"></span></div><div class="profile-extra-entries__text"><strong><a href="/users/2">peppy</a></strong> has received the gift of osu!supporter!</div></div><div class="profile-extra-entries__time"><time class="js-timeago" datetime="2026-07-06T14:34:12+00:00" title="2026-07-06T14:34:12+00:00">24 days ago</time></div></li><li class="profile-extra-entries__item"><div class="profile-extra-entries__detail"><div class="profile-extra-entries__icon profile-extra-entries__icon--pink"><span class="fas fa-gift"></span></div><div class="profile-extra-entries__text"><strong><a href="/users/2">peppy</a></strong> has received the gift of osu!supporter!</div></div><div class="profile-extra-entries__time"><time class="js-timeago" datetime="2026-07-01T11:23:07+00:00" title="2026-07-01T11:23:07+00:00">29 days ago</time></div></li><li class="profile-extra-entries__item u-contents"></li></ul></div></div></div><div class="js-sortable--page" data-page-id="beatmaps"><div class="page-extra"><div class="u-relative"><h2 class="title title--page-extra">Beatmaps</h2></div><div class="lazy-load"><h3 class="title title--page-extra-small">Favourite Beatmaps<span class="title__count">15</span></h3><div class="page-extra__beatmapsets js-audio--group"><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/2412244.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/2412244"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-4); --bg: url(&quot;https://assets.ppy.sh/beatmaps/2412244/covers/list.jpg?1759157730&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/2412244/covers/list@2x.jpg?1759157730&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-4); --bg: url(&quot;https://assets.ppy.sh/beatmaps/2412244/covers/card.jpg?1759157730&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/2412244/covers/card@2x.jpg?1759157730&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"><div class="beatmapset-panel__play-icon" title="This beatmap contains storyboard"><i class="fas fa-image"></i></div></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/2412244">Rift Walker</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/2412244">by Kry.exe</a><div class="beatmapset-panel__badge-container"><a class="beatmapset-badge beatmapset-badge--featured_artist" href="https://osu.ppy.sh/beatmaps/artists/tracks/11088">Featured Artist</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow">Locus 2025</div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="7777875" href="https://osu.ppy.sh/users/7777875">Ryuusei Aika</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 495,812"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>495.8K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 1,804"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>1.8K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2025-10-02T23:02:44Z" title="2025-10-02T23:02:44Z">3 Oct 2025</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/2412244"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(79, 250, 217);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(130, 255, 79);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(254, 150, 102);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(211, 71, 172);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(97, 95, 216);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/1583787.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/1583787"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-3); --bg: url(&quot;https://assets.ppy.sh/beatmaps/1583787/covers/list.jpg?1742238269&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/1583787/covers/list@2x.jpg?1742238269&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-3); --bg: url(&quot;https://assets.ppy.sh/beatmaps/1583787/covers/card.jpg?1742238269&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/1583787/covers/card@2x.jpg?1742238269&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/1583787">Magic Girl !!</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/1583787">by A-One feat. Shihori</a><div class="beatmapset-panel__badge-container"><a class="beatmapset-badge beatmapset-badge--featured_artist" href="https://osu.ppy.sh/beatmaps/artists/tracks/4290">Featured Artist</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow">東方紅魔郷　～ the Embodiment of Scarlet Devil.</div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="5710809" href="https://osu.ppy.sh/users/5710809">Sakurauchi Riko</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 221,541"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>221.5K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 455"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>455</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2025-03-24T21:44:30Z" title="2025-03-24T21:44:30Z">24 Mar 2025</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/1583787"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(253, 166, 101);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(255, 102, 108);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(233, 74, 147);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(154, 87, 206);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(121, 95, 217);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(77, 75, 190);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/1778741.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/1778741"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-5); --bg: url(&quot;https://assets.ppy.sh/beatmaps/1778741/covers/list.jpg?1682434395&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/1778741/covers/list@2x.jpg?1682434395&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-5); --bg: url(&quot;https://assets.ppy.sh/beatmaps/1778741/covers/card.jpg?1682434395&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/1778741/covers/card@2x.jpg?1682434395&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/1778741">Fallen</a><div class="beatmapset-panel__badge-container"><a class="beatmapset-badge beatmapset-badge--spotlight" href="https://osu.ppy.sh/wiki/en/Beatmap_Spotlights">Spotlight</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/1778741">by Zekk</a><div class="beatmapset-panel__badge-container"><a class="beatmapset-badge beatmapset-badge--featured_artist" href="https://osu.ppy.sh/beatmaps/artists/tracks/5970">Featured Artist</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow">EZ2AC : NIGHT TRAVELER</div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="531253" href="https://osu.ppy.sh/users/531253">CLSW</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 27,617"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>27.6K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 91"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>91</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2023-05-02T16:03:34Z" title="2023-05-02T16:03:34Z">2 May 2023</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/1778741"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!catch"><i class="fal fa-extra-mode-fruits"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(79, 218, 240);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(80, 255, 212);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(229, 243, 90);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(255, 120, 105);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(198, 69, 184);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/861.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/861"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-3); --bg: url(&quot;https://assets.ppy.sh/beatmaps/861/covers/list.jpg?1622018875&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/861/covers/list@2x.jpg?1622018875&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-3); --bg: url(&quot;https://assets.ppy.sh/beatmaps/861/covers/card.jpg?1622018875&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/861/covers/card@2x.jpg?1622018875&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/861">Apologize</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/861">by One Republic</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="5725" href="https://osu.ppy.sh/users/5725">Slezak</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 126,903"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>126.9K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 109"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>109</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2008-03-06T04:38:43Z" title="2008-03-06T04:38:43Z">6 Mar 2008</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/861"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(79, 244, 222);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(83, 255, 207);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(97, 255, 182);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/2459.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/2459"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-5); --bg: url(&quot;https://assets.ppy.sh/beatmaps/2459/covers/list.jpg?1622020081&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/2459/covers/list@2x.jpg?1622020081&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-5); --bg: url(&quot;https://assets.ppy.sh/beatmaps/2459/covers/card.jpg?1622020081&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/2459/covers/card@2x.jpg?1622020081&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/2459">Ryuuseigun</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/2459">by Nico Nico Douga</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow">Nico Nico Douga</div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="2" href="https://osu.ppy.sh/users/2">peppy</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 538,487"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>538.5K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 682"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>682</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2008-08-16T19:23:24Z" title="2008-08-16T19:23:24Z">16 Aug 2008</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/2459"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-approved-bg-hsl); --colour: var(--beatmapset-approved-colour);">Approved</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(255, 82, 111);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/1400282.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/1400282"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/1400282/covers/list.jpg?1650708589&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/1400282/covers/list@2x.jpg?1650708589&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/1400282/covers/card.jpg?1650708589&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/1400282/covers/card@2x.jpg?1650708589&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"><div class="beatmapset-panel__play-icon" title="This beatmap contains storyboard"><i class="fas fa-image"></i></div></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/1400282">On &amp; On (feat. Daniel Levi) (Cut Ver.)</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/1400282">by Cartoon</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="3906405" href="https://osu.ppy.sh/users/3906405">Sylas</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 3,831,629"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>3.8M</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 3,060"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>3.1K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2021-04-29T07:03:50Z" title="2021-04-29T07:03:50Z">29 Apr 2021</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/1400282"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(95, 255, 186);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(227, 243, 89);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(253, 162, 101);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(255, 107, 108);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(235, 75, 144);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><button type="button" class="show-more-link show-more-link--profile-page show-more-link--profile-page-beatmapsets"><span class="show-more-link__spinner"><span class="la-ball-clip-rotate"></span></span><span class="show-more-link__label"><span class="show-more-link__label-icon show-more-link__label-icon--left"><span class="fas fa-angle-down"></span></span><span class="show-more-link__label-text">show more</span><span class="show-more-link__label-icon show-more-link__label-icon--right"><span class="fas fa-angle-down"></span></span></span></button></div><h3 class="title title--page-extra-small">Ranked Beatmaps<span class="title__count">11</span></h3><div class="page-extra__beatmapsets js-audio--group"><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/8023.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/8023"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-1); --bg: url(&quot;https://assets.ppy.sh/beatmaps/8023/covers/list.jpg?1622026103&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/8023/covers/list@2x.jpg?1622026103&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-1); --bg: url(&quot;https://assets.ppy.sh/beatmaps/8023/covers/card.jpg?1622026103&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/8023/covers/card@2x.jpg?1622026103&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"><div class="beatmapset-panel__play-icon" title="This beatmap contains storyboard"><i class="fas fa-image"></i></div></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/8023">Baby Cruising Love</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/8023">by Perfume</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="2" href="https://osu.ppy.sh/users/2">peppy</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 298,149"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>298.1K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 207"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>207</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2009-07-12T18:05:08Z" title="2009-07-12T18:05:08Z">12 Jul 2009</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/8023"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(79, 247, 220);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(247, 233, 93);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/4887.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/4887"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-3); --bg: url(&quot;https://assets.ppy.sh/beatmaps/4887/covers/list.jpg?1622022407&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/4887/covers/list@2x.jpg?1622022407&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-3); --bg: url(&quot;https://assets.ppy.sh/beatmaps/4887/covers/card.jpg?1622022407&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/4887/covers/card@2x.jpg?1622022407&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"><div class="beatmapset-panel__play-icon" title="This beatmap contains video"><i class="fas fa-film"></i></div></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/4887">Coastal Tempo</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/4887">by 3rd Coast</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="2" href="https://osu.ppy.sh/users/2">peppy</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 98,361"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>98.4K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 39"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>39</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2009-02-27T20:57:15Z" title="2009-02-27T20:57:15Z">27 Feb 2009</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/4887"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(79, 211, 245);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(190, 248, 85);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(251, 187, 99);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/1184.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/1184"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/1184/covers/list.jpg?1622019159&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/1184/covers/list@2x.jpg?1622019159&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/1184/covers/card.jpg?1622019159&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/1184/covers/card@2x.jpg?1622019159&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"><div class="beatmapset-panel__play-icon" title="This beatmap contains video"><i class="fas fa-film"></i></div></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/1184">Ai Uta</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/1184">by GReeeeN</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="2" href="https://osu.ppy.sh/users/2">peppy</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 161,885"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>161.9K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 172"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>172</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2008-12-08T16:35:06Z" title="2008-12-08T16:35:06Z">8 Dec 2008</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/1184"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(79, 210, 245);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(246, 238, 92);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/3074.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/3074"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/3074/covers/list.jpg?1622020525&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/3074/covers/list@2x.jpg?1622020525&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/3074/covers/card.jpg?1622020525&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/3074/covers/card@2x.jpg?1622020525&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"><div class="beatmapset-panel__play-icon" title="This beatmap contains video"><i class="fas fa-film"></i></div></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/3074">Luv Flow</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/3074">by 3rd Coast</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow">DJMax</div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="2" href="https://osu.ppy.sh/users/2">peppy</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 59,826"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>59.8K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 33"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>33</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2008-11-10T15:03:04Z" title="2008-11-10T15:03:04Z">10 Nov 2008</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/3074"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(196, 248, 86);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(253, 165, 101);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/2459.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/2459"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-5); --bg: url(&quot;https://assets.ppy.sh/beatmaps/2459/covers/list.jpg?1622020081&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/2459/covers/list@2x.jpg?1622020081&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-5); --bg: url(&quot;https://assets.ppy.sh/beatmaps/2459/covers/card.jpg?1622020081&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/2459/covers/card@2x.jpg?1622020081&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/2459">Ryuuseigun</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/2459">by Nico Nico Douga</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow">Nico Nico Douga</div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="2" href="https://osu.ppy.sh/users/2">peppy</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 538,487"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>538.5K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 682"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>682</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2008-08-16T19:23:24Z" title="2008-08-16T19:23:24Z">16 Aug 2008</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/2459"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-approved-bg-hsl); --colour: var(--beatmapset-approved-colour);">Approved</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(255, 82, 111);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/184.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/184"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-4); --bg: url(&quot;https://assets.ppy.sh/beatmaps/184/covers/list.jpg?1622018243&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/184/covers/list@2x.jpg?1622018243&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-4); --bg: url(&quot;https://assets.ppy.sh/beatmaps/184/covers/card.jpg?1622018243&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/184/covers/card@2x.jpg?1622018243&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"><div class="beatmapset-panel__play-icon" title="This beatmap contains storyboard"><i class="fas fa-image"></i></div></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/184">Make Up! Make Up!</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/184">by Chatmonchy</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="2" href="https://osu.ppy.sh/users/2">peppy</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 1,639,353"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>1.6M</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 680"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>680</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2008-04-20T18:32:25Z" title="2008-04-20T18:32:25Z">20 Apr 2008</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/184"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(136, 254, 80);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(247, 228, 94);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><button type="button" class="show-more-link show-more-link--profile-page show-more-link--profile-page-beatmapsets"><span class="show-more-link__spinner"><span class="la-ball-clip-rotate"></span></span><span class="show-more-link__label"><span class="show-more-link__label-icon show-more-link__label-icon--left"><span class="fas fa-angle-down"></span></span><span class="show-more-link__label-text">show more</span><span class="show-more-link__label-icon show-more-link__label-icon--right"><span class="fas fa-angle-down"></span></span></span></button></div><h3 class="title title--page-extra-small">Guest Participation Beatmaps<span class="title__count">2</span></h3><div class="page-extra__beatmapsets js-audio--group"><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/10652.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/10652"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/10652/covers/list.jpg?1622029424&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/10652/covers/list@2x.jpg?1622029424&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/10652/covers/card.jpg?1622029424&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/10652/covers/card@2x.jpg?1622029424&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"><div class="beatmapset-panel__play-icon" title="This beatmap contains storyboard"><i class="fas fa-image"></i></div></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/10652">Twelve Days Of Christmas</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/10652">by John Denver &amp; The Muppets</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="1079" href="https://osu.ppy.sh/users/1079">LuigiHann</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 21,351"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>21.4K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 26"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>26</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2010-01-06T02:25:27Z" title="2010-01-06T02:25:27Z">6 Jan 2010</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/10652"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(141, 254, 80);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(249, 207, 97);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/2425.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/2425"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-1); --bg: url(&quot;https://assets.ppy.sh/beatmaps/2425/covers/list.jpg?1622020042&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/2425/covers/list@2x.jpg?1622020042&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-1); --bg: url(&quot;https://assets.ppy.sh/beatmaps/2425/covers/card.jpg?1622020042&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/2425/covers/card@2x.jpg?1622020042&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"><div class="beatmapset-panel__play-icon" title="This beatmap contains video"><i class="fas fa-film"></i></div></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/2425">Dramatic (TV Size)</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/2425">by YUKI</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow">Honey and Clover</div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="9199" href="https://osu.ppy.sh/users/9199">Remco32</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 238,634"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>238.6K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 70"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>70</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2008-08-10T09:11:55Z" title="2008-08-10T09:11:55Z">10 Aug 2008</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/2425"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(100, 255, 174);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(118, 255, 114);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(168, 251, 83);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(251, 194, 98);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div></div><h3 class="title title--page-extra-small">Graveyarded Beatmaps<span class="title__count">9</span></h3><div class="page-extra__beatmapsets js-audio--group"><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/855379.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/855379"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-1); --bg: url(&quot;https://assets.ppy.sh/beatmaps/855379/covers/list.jpg?1766818823&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/855379/covers/list@2x.jpg?1766818823&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-1); --bg: url(&quot;https://assets.ppy.sh/beatmaps/855379/covers/card.jpg?1766818823&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/855379/covers/card@2x.jpg?1766818823&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"><div class="beatmapset-panel__play-icon" title="This beatmap contains storyboard"><i class="fas fa-image"></i></div></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/855379">Lovefool 30ser ver</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/855379">by Perfume</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="2" href="https://osu.ppy.sh/users/2">peppy</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 10,373"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>10.4K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 80"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>80</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2025-11-29T06:42:50Z" title="2025-11-29T06:42:50Z">29 Nov 2025</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/855379"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-graveyard-bg-hsl); --colour: var(--beatmapset-graveyard-colour);">Graveyard</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(79, 222, 238);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(79, 223, 237);"></div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!mania"><i class="fal fa-extra-mode-mania"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: #AAAAAA;"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/75429.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/75429"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-3); --bg: url(&quot;https://assets.ppy.sh/beatmaps/75429/covers/list.jpg?1571225245&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/75429/covers/list@2x.jpg?1571225245&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-3); --bg: url(&quot;https://assets.ppy.sh/beatmaps/75429/covers/card.jpg?1571225245&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/75429/covers/card@2x.jpg?1571225245&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/75429">Under the Moon (Earthlight Extended Mix)</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/75429">by DJ SkyRiser / JOYH-TV vs. Lix</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="2" href="https://osu.ppy.sh/users/2">peppy</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 246"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>246</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 57"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>57</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2019-10-16T11:26:55Z" title="2019-10-16T11:26:55Z">16 Oct 2019</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/75429"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-graveyard-bg-hsl); --colour: var(--beatmapset-graveyard-colour);">Graveyard</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(79, 250, 217);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><button type="button" class="show-more-link show-more-link--profile-page show-more-link--profile-page-beatmapsets"><span class="show-more-link__spinner"><span class="la-ball-clip-rotate"></span></span><span class="show-more-link__label"><span class="show-more-link__label-icon show-more-link__label-icon--left"><span class="fas fa-angle-down"></span></span><span class="show-more-link__label-text">show more</span><span class="show-more-link__label-icon show-more-link__label-icon--right"><span class="fas fa-angle-down"></span></span></span></button></div><h3 class="title title--page-extra-small">Nominated Ranked Beatmaps<span class="title__count">183</span></h3><div class="page-extra__beatmapsets js-audio--group"><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/8986.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/8986"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-4); --bg: url(&quot;https://assets.ppy.sh/beatmaps/8986/covers/list.jpg?1631329119&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/8986/covers/list@2x.jpg?1631329119&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-4); --bg: url(&quot;https://assets.ppy.sh/beatmaps/8986/covers/card.jpg?1631329119&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/8986/covers/card@2x.jpg?1631329119&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/8986">Power of Flower</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/8986">by Itou Shizuka</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow">Hayate no Gotoku</div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="73453" href="https://osu.ppy.sh/users/73453">taka1235</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 85,005"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>85K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 60"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>60</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2009-09-26T03:38:31Z" title="2009-09-26T03:38:31Z">26 Sep 2009</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/8986"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(142, 254, 80);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(218, 245, 88);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/8328.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/8328"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-0); --bg: url(&quot;https://assets.ppy.sh/beatmaps/8328/covers/list.jpg?1622026507&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/8328/covers/list@2x.jpg?1622026507&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-0); --bg: url(&quot;https://assets.ppy.sh/beatmaps/8328/covers/card.jpg?1622026507&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/8328/covers/card@2x.jpg?1622026507&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"><div class="beatmapset-panel__play-icon" title="This beatmap contains storyboard"><i class="fas fa-image"></i></div></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/8328">He Xie Ni Quan Jia</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/8328">by GreenDAM</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="94258" href="https://osu.ppy.sh/users/94258">zerosyn</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 645,593"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>645.6K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 318"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>318</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2009-09-26T02:54:46Z" title="2009-09-26T02:54:46Z">26 Sep 2009</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/8328"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(79, 229, 233);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(151, 253, 81);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(247, 232, 93);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/6866.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/6866"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/6866/covers/list.jpg?1622024767&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/6866/covers/list@2x.jpg?1622024767&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/6866/covers/card.jpg?1622024767&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/6866/covers/card@2x.jpg?1622024767&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"><div class="beatmapset-panel__play-icon" title="This beatmap contains storyboard"><i class="fas fa-image"></i></div></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/6866">PaPaPa Love</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/6866">by Taiko no Tatsujin</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="4934" href="https://osu.ppy.sh/users/4934">mattyu007</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 89,880"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>89.9K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 63"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>63</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2009-09-21T18:40:55Z" title="2009-09-21T18:40:55Z">21 Sep 2009</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/6866"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(95, 255, 185);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(195, 248, 86);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(247, 228, 94);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(253, 164, 101);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/6342.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/6342"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-0); --bg: url(&quot;https://assets.ppy.sh/beatmaps/6342/covers/list.jpg?1650602507&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/6342/covers/list@2x.jpg?1650602507&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-0); --bg: url(&quot;https://assets.ppy.sh/beatmaps/6342/covers/card.jpg?1650602507&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/6342/covers/card@2x.jpg?1650602507&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/6342">Itsumademo Issho ni</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/6342">by Nakai Kazuya (Gaomon)</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow">Digimon Savers</div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="17938" href="https://osu.ppy.sh/users/17938">Ekaru</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 100,624"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>100.6K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 73"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>73</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2009-09-21T16:46:38Z" title="2009-09-21T16:46:38Z">21 Sep 2009</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/6342"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(79, 229, 233);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(130, 255, 79);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(249, 211, 96);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/5780.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/5780"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/5780/covers/list.jpg?1622023521&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/5780/covers/list@2x.jpg?1622023521&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/5780/covers/card.jpg?1622023521&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/5780/covers/card@2x.jpg?1622023521&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/5780">One Night Carnival</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/5780">by Kei Imai</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow">Osu! Tatakae! Ouendan!</div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="30655" href="https://osu.ppy.sh/users/30655">MetalMario201</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 58,190"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>58.2K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 63"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>63</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2009-04-11T16:21:09Z" title="2009-04-11T16:21:09Z">11 Apr 2009</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/5780"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(161, 252, 82);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(188, 249, 85);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(244, 240, 92);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(246, 237, 92);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><div class="beatmapset-panel beatmapset-panel--size-normal js-audio--player" data-audio-url="https://b.ppy.sh/preview/4406.mp3" style="--beatmaps-popup-transition-duration: 150ms;"><a class="beatmapset-panel__cover-container" href="https://osu.ppy.sh/beatmapsets/4406"><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--play"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/4406/covers/list.jpg?1650601601&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/4406/covers/list@2x.jpg?1650601601&quot;);"></div></div><div class="beatmapset-panel__cover-col beatmapset-panel__cover-col--info"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/4406/covers/card.jpg?1650601601&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/4406/covers/card@2x.jpg?1650601601&quot;);"></div></div></a><div class="beatmapset-panel__content"><div class="beatmapset-panel__play-container"><button class="beatmapset-panel__play js-audio--play" type="button"><span class="play-button"></span></button><div class="beatmapset-panel__play-progress"><div class="circular-progress circular-progress--beatmapset-panel" title="0 / 1"><div class="circular-progress__label">1</div><div class="circular-progress__slice"><div class="circular-progress__circle"></div><div class="circular-progress__circle circular-progress__circle--fill"></div></div></div></div><div class="beatmapset-panel__play-icons"></div></div><div class="beatmapset-panel__info"><div class="beatmapset-panel__info-row beatmapset-panel__info-row--title"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/4406">The Office Theme</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--artist"><a class="beatmapset-panel__main-link u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/4406">by The Scrantones</a><div class="beatmapset-panel__badge-container"></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--source"><div class="u-ellipsis-overflow">The Office (American)</div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--mapper"><div class="u-ellipsis-overflow">mapped by <a class="js-usercard beatmapset-panel__mapper-link u-hover" data-user-id="56708" href="https://osu.ppy.sh/users/56708">0_o</a></div></div><div class="beatmapset-panel__info-row beatmapset-panel__info-row--stats"><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--play-count" title="Playcount: 651,583"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-play-circle"></i></span><span>651.6K</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--favourite-count" title="Favourites: 386"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw far fa-heart"></i></span><span>386</span></div><div class="beatmapset-panel__stats-item beatmapset-panel__stats-item--date"><span class="beatmapset-panel__stats-item-icon"><i class="fa-fw fas fa-check-circle"></i></span><time class="js-tooltip-time" datetime="2009-03-21T04:24:07Z" title="2009-03-21T04:24:07Z">21 Mar 2009</time></div></div><a class="beatmapset-panel__info-row beatmapset-panel__info-row--extra" href="https://osu.ppy.sh/beatmapsets/4406"><div class="beatmapset-panel__extra-item"><div class="beatmapset-status beatmapset-status--panel" style="--bg-hsl: var(--beatmapset-ranked-bg-hsl); --colour: var(--beatmapset-ranked-colour);">Ranked</div></div><div class="beatmapset-panel__extra-item beatmapset-panel__extra-item--dots"><div class="beatmapset-panel__beatmap-icon" title="osu!"><i class="fal fa-extra-mode-osu"></i></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(79, 227, 235);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(114, 255, 131);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(246, 240, 92);"></div><div class="beatmapset-panel__beatmap-dot" style="--bg: rgb(255, 120, 105);"></div></div></a></div><div class="beatmapset-panel__menu-container"><div class="beatmapset-panel__menu"><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="sign in to favourite this beatmap"><span class="far fa-heart"></span></span><span class="beatmapset-panel__menu-item beatmapset-panel__menu-item--disabled" title="you need to sign in before downloading any beatmaps!"><span class="fas fa-file-download"></span></span></div></div></div><button class="beatmapset-panel__mobile-expand" type="button"><span class="fas fa-angle-down"></span></button></div><button type="button" class="show-more-link show-more-link--profile-page show-more-link--profile-page-beatmapsets"><span class="show-more-link__spinner"><span class="la-ball-clip-rotate"></span></span><span class="show-more-link__label"><span class="show-more-link__label-icon show-more-link__label-icon--left"><span class="fas fa-angle-down"></span></span><span class="show-more-link__label-text">show more</span><span class="show-more-link__label-icon show-more-link__label-icon--right"><span class="fas fa-angle-down"></span></span></span></button></div></div></div></div><div class="js-sortable--page" data-page-id="historical"><div class="page-extra"><div class="u-relative"><h2 class="title title--page-extra">Historical</h2></div><div class="lazy-load"><h3 class="title title--page-extra-small">Play History</h3><div class="page-extra__chart"><div class="line-chart line-chart--profile-page"><svg width="900" height="250"><g class="line-chart__wrapper" transform="translate(60, 20)"><g class="line-chart__axis line-chart__axis--x" fill="none" font-size="10" font-family="sans-serif" text-anchor="middle" transform="translate(0, 180)"><path class="domain u-hidden" stroke="currentColor" d="M0.5,0.5H780.5"></path><g class="tick" opacity="1" transform="translate(11.073154560188597,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2008</text></g><g class="tick" opacity="1" transform="translate(53.135921614851924,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2009</text></g><g class="tick" opacity="1" transform="translate(95.08376307646972,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2010</text></g><g class="tick" opacity="1" transform="translate(137.03160453808752,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2011</text></g><g class="tick" opacity="1" transform="translate(178.97944599970532,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2012</text></g><g class="tick" opacity="1" transform="translate(221.04221305436863,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2013</text></g><g class="tick" opacity="1" transform="translate(262.99005451598646,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2014</text></g><g class="tick" opacity="1" transform="translate(304.9378959776042,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2015</text></g><g class="tick" opacity="1" transform="translate(346.885737439222,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2016</text></g><g class="tick" opacity="1" transform="translate(388.94850449388537,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2017</text></g><g class="tick" opacity="1" transform="translate(430.8963459555032,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2018</text></g><g class="tick" opacity="1" transform="translate(472.84418741712096,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2019</text></g><g class="tick" opacity="1" transform="translate(514.7920288787387,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2020</text></g><g class="tick" opacity="1" transform="translate(556.8547959334021,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2021</text></g><g class="tick" opacity="1" transform="translate(598.8026373950199,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2022</text></g><g class="tick" opacity="1" transform="translate(640.7504788566376,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2023</text></g><g class="tick" opacity="1" transform="translate(682.6983203182555,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2024</text></g><g class="tick" opacity="1" transform="translate(724.7610873729188,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2025</text></g><g class="tick" opacity="1" transform="translate(766.7089288345367,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2026</text></g></g><g class="line-chart__axis line-chart__axis--y" fill="none" font-size="10" font-family="sans-serif" text-anchor="end"><path class="domain u-hidden" stroke="currentColor" d="M-6,180.5H0.5V0.5H-6"></path><g class="tick" opacity="1" transform="translate(0,180.5)"><line stroke="currentColor" x2="780" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" x="-3" dy="0.32em" class="line-chart__tick-text">0</text></g><g class="tick" opacity="1" transform="translate(0,146.34440227703985)"><line stroke="currentColor" x2="780" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" x="-3" dy="0.32em" class="line-chart__tick-text">100</text></g><g class="tick" opacity="1" transform="translate(0,112.1888045540797)"><line stroke="currentColor" x2="780" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" x="-3" dy="0.32em" class="line-chart__tick-text">200</text></g><g class="tick" opacity="1" transform="translate(0,78.03320683111956)"><line stroke="currentColor" x2="780" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" x="-3" dy="0.32em" class="line-chart__tick-text">300</text></g><g class="tick" opacity="1" transform="translate(0,43.87760910815939)"><line stroke="currentColor" x2="780" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" x="-3" dy="0.32em" class="line-chart__tick-text">400</text></g><g class="tick" opacity="1" transform="translate(0,9.722011385199247)"><line stroke="currentColor" x2="780" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" x="-3" dy="0.32em" class="line-chart__tick-text">500</text></g></g><path class="line-chart__line" d="M0,15.028L3.563,49.867L7.01,147.894L10.573,158.482L14.136,87.097L17.469,90.854L21.031,0L24.479,66.945L28.042,139.013L31.49,160.19L35.052,76.509L38.615,88.463L42.063,146.528L45.625,139.355L49.073,112.03L52.636,144.137L56.199,147.894L59.417,134.573L62.979,158.482L66.427,169.07L69.99,126.034L73.437,137.306L77,151.309L80.563,165.313L84.011,43.036L87.573,177.268L91.021,178.634L94.584,179.317L98.146,171.461L101.364,173.169L104.927,175.56L108.375,180L111.938,180L115.385,180L118.948,171.803L122.511,179.658L125.958,180L129.521,161.898L132.969,179.658L136.532,180L140.094,180L143.312,180L146.875,180L150.323,180L153.885,180L157.333,180L160.896,180L164.459,180L167.906,180L171.469,180L174.917,180L178.479,180L182.042,180L185.375,180L188.938,179.317L192.385,180L195.948,180L199.396,180L202.959,180L206.521,172.486L209.969,115.446L213.532,175.218L216.98,178.975L220.542,178.975L224.105,159.165L227.323,113.055L230.886,178.634L234.333,179.317L237.896,178.634L241.344,175.56L244.906,171.12L248.469,127.059L251.917,169.412L255.48,170.095L258.927,112.713L262.49,171.461L266.053,141.404L269.271,87.78L272.833,162.239L276.281,172.827L279.844,136.964L283.292,126.034L286.854,173.51L290.417,178.634L293.865,172.486L297.427,170.436L300.875,164.63L304.438,171.803L308.001,174.877L311.219,171.803L314.781,168.387L318.229,174.877L321.792,177.951L325.239,171.12L328.802,167.704L332.365,168.046L335.813,144.478L339.375,177.268L342.823,180L346.386,175.56L349.948,169.753L353.281,172.827L356.844,156.433L360.292,170.778L363.854,179.317L367.302,179.317L370.865,179.317L374.428,167.362L377.875,178.975L381.438,180L384.886,176.926L388.449,162.239L392.011,180L395.229,179.317L398.792,179.658L402.24,180L405.802,180L409.25,180L412.813,179.317L416.375,180L419.823,167.704L423.386,168.729L426.834,177.951L430.396,180L433.959,180L437.177,178.634L440.74,179.317L444.187,179.317L447.75,180L451.198,169.753L454.761,179.658L458.323,179.317L461.771,176.926L465.334,179.658L468.781,159.507L472.344,180L475.907,177.951L479.125,180L482.687,177.951L486.135,179.658L489.698,180L493.146,179.658L496.708,168.729L500.271,180L503.719,178.292L507.282,178.634L510.729,178.292L514.292,177.951L517.855,180L521.188,178.634L524.75,176.926L528.198,177.268L531.761,176.926L535.208,177.268L538.771,179.317L542.334,179.658L545.782,178.975L549.344,179.317L552.792,179.658L556.355,174.535L559.917,179.658L563.135,179.658L566.698,178.634L570.146,177.268L573.709,170.778L577.156,175.901L580.719,176.926L584.282,178.975L587.729,178.634L591.292,179.317L594.74,177.609L598.303,175.56L601.865,172.827L605.083,165.996L608.646,177.951L612.094,180L615.656,179.317L619.104,174.535L622.667,179.658L626.23,176.584L629.677,177.268L633.24,174.877L636.688,170.095L640.25,179.658L643.813,175.56L647.031,178.634L650.594,180L654.042,179.658L657.604,179.658L661.052,179.658L664.615,178.975L668.177,179.317L671.625,179.658L675.188,177.268L678.636,177.951L682.198,157.799L685.761,180L689.094,178.975L692.657,179.658L696.104,180L699.667,180L703.115,178.634L706.677,179.317L710.24,178.975L713.688,180L717.251,180L720.698,179.658L724.261,179.317L727.824,179.317L731.042,178.634L734.604,179.658L738.052,180L741.615,179.658L745.063,179.317L748.625,179.317L752.188,170.436L755.636,177.609L759.198,180L762.646,175.901L766.209,179.658L769.772,178.975L772.99,179.658L776.552,179.317L780,179.658"></path></g></svg><div class="line-chart__hover-area" style="inset: 20px 60px 50px;"><div class="line-chart__hover" data-visibility="hidden"><div class="line-chart__hover-line" style=""></div><div class="line-chart__hover-circle" style=""></div><div class="line-chart__hover-info-box" data-float="left"><div class="line-chart__hover-info-box-text line-chart__hover-info-box-text--x"></div><div class="line-chart__hover-info-box-text line-chart__hover-info-box-text--y"></div></div></div></div></div></div><h3 class="title title--page-extra-small">Most Played Beatmaps<span class="title__count">464</span></h3><div><div class="beatmap-playcount"><a class="beatmap-playcount__cover" href="https://osu.ppy.sh/beatmapsets/118#osu/259"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-4); --bg: url(&quot;https://assets.ppy.sh/beatmaps/118/covers/list.jpg?1622018064&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/118/covers/list@2x.jpg?1622018064&quot;);"></div><div class="beatmap-playcount__cover-count"><div class="beatmap-playcount__count" title="times played"><span class="beatmap-playcount__count-icon"><span class="fas fa-play"></span></span>618</div></div></a><div class="beatmap-playcount__detail"><div class="beatmap-playcount__info"><div class="beatmap-playcount__info-row u-ellipsis-overflow"><a class="beatmap-playcount__title" href="https://osu.ppy.sh/beatmapsets/118#osu/259">Survival dAnce ~no no cry more~ [Insane] <span class="beatmap-playcount__title-artist">by TRF</span></a></div><div class="beatmap-playcount__info-row u-ellipsis-overflow"><span class="beatmap-playcount__artist">by <strong>TRF</strong></span> <span class="beatmap-playcount__mapper">mapped by <a class="js-usercard beatmap-playcount__mapper-link" data-user-id="431" href="https://osu.ppy.sh/users/431">Echo</a></span></div></div><div class="beatmap-playcount__detail-count"><div class="beatmap-playcount__count" title="times played"><span class="beatmap-playcount__count-icon"><span class="fas fa-play"></span></span>618</div></div></div></div><div class="beatmap-playcount"><a class="beatmap-playcount__cover" href="https://osu.ppy.sh/beatmapsets/118#osu/258"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-4); --bg: url(&quot;https://assets.ppy.sh/beatmaps/118/covers/list.jpg?1622018064&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/118/covers/list@2x.jpg?1622018064&quot;);"></div><div class="beatmap-playcount__cover-count"><div class="beatmap-playcount__count" title="times played"><span class="beatmap-playcount__count-icon"><span class="fas fa-play"></span></span>275</div></div></a><div class="beatmap-playcount__detail"><div class="beatmap-playcount__info"><div class="beatmap-playcount__info-row u-ellipsis-overflow"><a class="beatmap-playcount__title" href="https://osu.ppy.sh/beatmapsets/118#osu/258">Survival dAnce ~no no cry more~ [Hard] <span class="beatmap-playcount__title-artist">by TRF</span></a></div><div class="beatmap-playcount__info-row u-ellipsis-overflow"><span class="beatmap-playcount__artist">by <strong>TRF</strong></span> <span class="beatmap-playcount__mapper">mapped by <a class="js-usercard beatmap-playcount__mapper-link" data-user-id="431" href="https://osu.ppy.sh/users/431">Echo</a></span></div></div><div class="beatmap-playcount__detail-count"><div class="beatmap-playcount__count" title="times played"><span class="beatmap-playcount__count-icon"><span class="fas fa-play"></span></span>275</div></div></div></div><div class="beatmap-playcount"><a class="beatmap-playcount__cover" href="https://osu.ppy.sh/beatmapsets/80#osu/182"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/80/covers/list.jpg?1622017992&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/80/covers/list@2x.jpg?1622017992&quot;);"></div><div class="beatmap-playcount__cover-count"><div class="beatmap-playcount__count" title="times played"><span class="beatmap-playcount__count-icon"><span class="fas fa-play"></span></span>237</div></div></a><div class="beatmap-playcount__detail"><div class="beatmap-playcount__info"><div class="beatmap-playcount__info-row u-ellipsis-overflow"><a class="beatmap-playcount__title" href="https://osu.ppy.sh/beatmapsets/80#osu/182">Sakuranbo [Hard] <span class="beatmap-playcount__title-artist">by Ai Otsuka</span></a></div><div class="beatmap-playcount__info-row u-ellipsis-overflow"><span class="beatmap-playcount__artist">by <strong>Ai Otsuka</strong></span> <span class="beatmap-playcount__mapper">mapped by <a class="js-usercard beatmap-playcount__mapper-link" data-user-id="431" href="https://osu.ppy.sh/users/431">Echo</a></span></div></div><div class="beatmap-playcount__detail-count"><div class="beatmap-playcount__count" title="times played"><span class="beatmap-playcount__count-icon"><span class="fas fa-play"></span></span>237</div></div></div></div><div class="beatmap-playcount"><a class="beatmap-playcount__cover" href="https://osu.ppy.sh/beatmapsets/68103#osu/197337"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-3); --bg: url(&quot;https://assets.ppy.sh/beatmaps/68103/covers/list.jpg?1650615223&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/68103/covers/list@2x.jpg?1650615223&quot;);"></div><div class="beatmap-playcount__cover-count"><div class="beatmap-playcount__count" title="times played"><span class="beatmap-playcount__count-icon"><span class="fas fa-play"></span></span>235</div></div></a><div class="beatmap-playcount__detail"><div class="beatmap-playcount__info"><div class="beatmap-playcount__info-row u-ellipsis-overflow"><a class="beatmap-playcount__title" href="https://osu.ppy.sh/beatmapsets/68103#osu/197337">Platinum (TV Size) [Insane] <span class="beatmap-playcount__title-artist">by Sakamoto Maaya</span></a></div><div class="beatmap-playcount__info-row u-ellipsis-overflow"><span class="beatmap-playcount__artist">by <strong>Sakamoto Maaya</strong></span> <span class="beatmap-playcount__mapper">mapped by <a class="js-usercard beatmap-playcount__mapper-link" data-user-id="959763" href="https://osu.ppy.sh/users/959763">Flask</a></span></div></div><div class="beatmap-playcount__detail-count"><div class="beatmap-playcount__count" title="times played"><span class="beatmap-playcount__count-icon"><span class="fas fa-play"></span></span>235</div></div></div></div><div class="beatmap-playcount"><a class="beatmap-playcount__cover" href="https://osu.ppy.sh/beatmapsets/96422#osu/258467"><div class="beatmapset-cover beatmapset-cover--full" style="--bg-default: var(--bg-default-2); --bg: url(&quot;https://assets.ppy.sh/beatmaps/96422/covers/list.jpg?1622064950&quot;); --bg-2x: url(&quot;https://assets.ppy.sh/beatmaps/96422/covers/list@2x.jpg?1622064950&quot;);"></div><div class="beatmap-playcount__cover-count"><div class="beatmap-playcount__count" title="times played"><span class="beatmap-playcount__count-icon"><span class="fas fa-play"></span></span>178</div></div></a><div class="beatmap-playcount__detail"><div class="beatmap-playcount__info"><div class="beatmap-playcount__info-row u-ellipsis-overflow"><a class="beatmap-playcount__title" href="https://osu.ppy.sh/beatmapsets/96422#osu/258467">The Sound of San Francisco [San Francisco] <span class="beatmap-playcount__title-artist">by Global Deejays</span></a></div><div class="beatmap-playcount__info-row u-ellipsis-overflow"><span class="beatmap-playcount__artist">by <strong>Global Deejays</strong></span> <span class="beatmap-playcount__mapper">mapped by <a class="js-usercard beatmap-playcount__mapper-link" data-user-id="553656" href="https://osu.ppy.sh/users/553656">Sey</a></span></div></div><div class="beatmap-playcount__detail-count"><div class="beatmap-playcount__count" title="times played"><span class="beatmap-playcount__count-icon"><span class="fas fa-play"></span></span>178</div></div></div></div><button type="button" class="show-more-link show-more-link--profile-page"><span class="show-more-link__spinner"><span class="la-ball-clip-rotate"></span></span><span class="show-more-link__label"><span class="show-more-link__label-icon show-more-link__label-icon--left"><span class="fas fa-angle-down"></span></span><span class="show-more-link__label-text">show more</span><span class="show-more-link__label-icon show-more-link__label-icon--right"><span class="fas fa-angle-down"></span></span></span></button></div><h3 class="title title--page-extra-small">Recent Plays (24h)<span class="title__count">0</span></h3><div class="play-detail-list u-relative"></div><h3 class="title title--page-extra-small">Replays Watched History</h3><div class="page-extra__chart"><div class="line-chart line-chart--profile-page"><svg width="900" height="250"><g class="line-chart__wrapper" transform="translate(60, 20)"><g class="line-chart__axis line-chart__axis--x" fill="none" font-size="10" font-family="sans-serif" text-anchor="middle" transform="translate(0, 180)"><path class="domain u-hidden" stroke="currentColor" d="M0.5,0.5H780.5"></path><g class="tick" opacity="1" transform="translate(19.339833696297763,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2013</text></g><g class="tick" opacity="1" transform="translate(75.70490991882795,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2014</text></g><g class="tick" opacity="1" transform="translate(132.06998614135816,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2015</text></g><g class="tick" opacity="1" transform="translate(188.43506236388833,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2016</text></g><g class="tick" opacity="1" transform="translate(244.95456345278163,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2017</text></g><g class="tick" opacity="1" transform="translate(301.3196396753118,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2018</text></g><g class="tick" opacity="1" transform="translate(357.684715897842,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2019</text></g><g class="tick" opacity="1" transform="translate(414.04979212037216,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2020</text></g><g class="tick" opacity="1" transform="translate(470.5692932092655,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2021</text></g><g class="tick" opacity="1" transform="translate(526.9343694317957,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2022</text></g><g class="tick" opacity="1" transform="translate(583.2994456543258,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2023</text></g><g class="tick" opacity="1" transform="translate(639.664521876856,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2024</text></g><g class="tick" opacity="1" transform="translate(696.1840229657494,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2025</text></g><g class="tick" opacity="1" transform="translate(752.5490991882796,0)"><line stroke="currentColor" y2="-180" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" y="5" dy="0.71em" style="text-anchor: start;" transform="rotate(45) translate(5, 0)" class="line-chart__tick-text line-chart__tick-text--strong">Jan 2026</text></g></g><g class="line-chart__axis line-chart__axis--y" fill="none" font-size="10" font-family="sans-serif" text-anchor="end"><path class="domain u-hidden" stroke="currentColor" d="M-6,180.5H0.5V0.5H-6"></path><g class="tick" opacity="1" transform="translate(0,180.5)"><line stroke="currentColor" x2="780" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" x="-3" dy="0.32em" class="line-chart__tick-text">0</text></g><g class="tick" opacity="1" transform="translate(0,123.89622641509435)"><line stroke="currentColor" x2="780" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" x="-3" dy="0.32em" class="line-chart__tick-text">200</text></g><g class="tick" opacity="1" transform="translate(0,67.29245283018868)"><line stroke="currentColor" x2="780" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" x="-3" dy="0.32em" class="line-chart__tick-text">400</text></g><g class="tick" opacity="1" transform="translate(0,10.688679245283016)"><line stroke="currentColor" x2="780" class="line-chart__tick-line line-chart__tick-line--default"></line><text fill="currentColor" x="-3" dy="0.32em" class="line-chart__tick-text">600</text></g></g><path class="line-chart__line" d="M0,172.925L4.633,172.075L9.42,180L14.053,180L18.84,179.717L23.627,179.717L27.951,176.038L32.738,180L37.371,180L42.158,180L46.791,180L51.578,180L56.365,179.717L60.998,179.717L65.785,179.434L70.418,179.717L75.205,179.717L79.992,178.868L84.316,179.434L89.103,179.151L93.736,179.717L98.523,178.585L103.156,179.717L107.943,179.717L112.73,180L117.363,179.717L122.15,179.717L126.783,179.434L131.57,179.434L136.357,179.434L140.681,179.434L145.468,179.434L150.101,178.302L154.888,180L159.521,176.604L164.308,175.189L169.095,170.377L173.728,155.943L178.515,179.717L183.148,179.151L187.935,178.868L192.722,178.019L197.201,179.151L201.988,180L206.62,178.585L211.408,179.717L216.04,179.434L220.828,179.434L225.615,179.717L230.247,165.283L235.035,179.434L239.667,179.151L244.455,179.717L249.242,179.717L253.566,179.717L258.353,179.151L262.986,179.717L267.773,179.717L272.405,179.717L277.193,179.717L281.98,179.434L286.613,177.453L291.4,179.151L296.032,179.717L300.82,178.868L305.607,179.717L309.931,178.585L314.718,180L319.351,178.868L324.138,178.868L328.771,177.736L333.558,0L338.345,179.434L342.978,178.868L347.765,180L352.398,179.434L357.185,179.717L361.972,179.717L366.296,180L371.083,179.434L375.716,179.151L380.503,179.434L385.136,179.717L389.923,180L394.71,180L399.343,179.717L404.13,180L408.763,179.151L413.55,179.717L418.337,179.434L422.815,179.717L427.602,179.434L432.235,179.717L437.022,147.453L441.655,179.717L446.442,178.868L451.229,176.321L455.862,179.717L460.649,178.302L465.282,180L470.069,179.434L474.856,179.717L479.18,179.717L483.968,179.434L488.6,179.717L493.387,179.434L498.02,180L502.807,179.717L507.595,179.717L512.227,180L517.014,180L521.647,179.151L526.434,180L531.222,180L535.545,179.717L540.333,179.434L544.965,179.717L549.753,179.434L554.385,179.434L559.172,180L563.96,179.717L568.592,180L573.38,179.434L578.012,176.887L582.799,179.717L587.587,179.151L591.911,180L596.698,180L601.33,176.038L606.118,178.585L610.75,180L615.538,178.868L620.325,179.717L624.957,180L629.745,179.717L634.377,180L639.165,179.434L643.952,176.887L648.43,178.868L653.217,179.151L657.85,180L662.637,179.717L667.27,176.321L672.057,179.151L676.844,180L681.477,180L686.264,179.434L690.897,179.717L695.684,180L700.471,180L704.795,179.434L709.582,180L714.215,180L719.002,180L723.635,179.717L728.422,180L733.209,180L737.842,180L742.629,180L747.262,179.717L752.049,179.717L756.836,164.717L761.16,179.151L765.947,179.434L770.58,180L775.367,180L780,179.717"></path></g></svg><div class="line-chart__hover-area" style="inset: 20px 60px 50px;"><div class="line-chart__hover" data-visibility="hidden"><div class="line-chart__hover-line" style=""></div><div class="line-chart__hover-circle" style=""></div><div class="line-chart__hover-info-box" data-float="left"><div class="line-chart__hover-info-box-text line-chart__hover-info-box-text--x"></div><div class="line-chart__hover-info-box-text line-chart__hover-info-box-text--y"></div></div></div></div></div></div><h3 class="title title--page-extra-small">Most Watched Replays<span class="title__count">61</span></h3><div class="play-detail-list"><div class="play-detail"><a class="play-detail__bg-link" href="https://osu.ppy.sh/scores/520067808"></a><div class="play-detail__group play-detail__group--top"><div class="play-detail__icon play-detail__icon--main"><div class="score-rank score-rank--full score-rank--A"></div></div><div class="play-detail__detail"><a class="play-detail__title u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/314#osu/1409">One Night Carnival <small class="play-detail__artist">by Kishidan</small></a><div class="play-detail__beatmap-and-time"><span class="play-detail__beatmap"><span class="fal fa-extra-mode-osu"></span> Hard</span><span class="play-detail__time"><time class="js-timeago" datetime="2017-10-28T04:13:21Z" title="2017-10-28T04:13:21Z">9 years ago</time></span></div></div></div><div class="play-detail__group play-detail__group--bottom"><div class="play-detail__score-detail"><div class="play-detail__icon play-detail__icon--extra"><div class="score-rank score-rank--full score-rank--A"></div></div><div class="play-detail__score-detail-top-right"><div class="play-detail__accuracy-and-weighted-pp"><span class="play-detail__accuracy">96.71%</span><span class="play-detail__weighted-pp u-hover"><span title="38.168">38pp</span></span></div></div></div><div class="play-detail__mods-pp"><div class="play-detail__mods"><div class="mod mod--type-Conversion" title="Classic"><div class="mod__icon mod__icon--CL" data-acronym="CL"></div></div></div><div class="play-detail__pp play-detail__pp--watch-count"><span><small><span class="fas fa-eye"></span></small> 18</span></div></div><div class="play-detail__more"><button class="popup-menu" type="button"><span class="fas fa-ellipsis-v"></span></button></div></div></div><div class="play-detail"><a class="play-detail__bg-link" href="https://osu.ppy.sh/scores/519939300"></a><div class="play-detail__group play-detail__group--top"><div class="play-detail__icon play-detail__icon--main"><div class="score-rank score-rank--full score-rank--B"></div></div><div class="play-detail__detail"><a class="play-detail__title u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/170#osu/426">Universal Dance <small class="play-detail__artist">by Laugh and Beats</small></a><div class="play-detail__beatmap-and-time"><span class="play-detail__beatmap"><span class="fal fa-extra-mode-osu"></span> Hard</span><span class="play-detail__time"><time class="js-timeago" datetime="2017-10-28T02:20:34Z" title="2017-10-28T02:20:34Z">9 years ago</time></span></div></div></div><div class="play-detail__group play-detail__group--bottom"><div class="play-detail__score-detail"><div class="play-detail__icon play-detail__icon--extra"><div class="score-rank score-rank--full score-rank--B"></div></div><div class="play-detail__score-detail-top-right"><div class="play-detail__accuracy-and-weighted-pp"><span class="play-detail__accuracy">88.05%</span><span class="play-detail__weighted-pp u-hover"><span title="24.865">25pp</span></span></div></div></div><div class="play-detail__mods-pp"><div class="play-detail__mods"><div class="mod mod--type-Conversion" title="Classic"><div class="mod__icon mod__icon--CL" data-acronym="CL"></div></div></div><div class="play-detail__pp play-detail__pp--watch-count"><span><small><span class="fas fa-eye"></span></small> 9</span></div></div><div class="play-detail__more"><button class="popup-menu" type="button"><span class="fas fa-ellipsis-v"></span></button></div></div></div><div class="play-detail"><a class="play-detail__bg-link" href="https://osu.ppy.sh/scores/1938537762"></a><div class="play-detail__group play-detail__group--top"><div class="play-detail__icon play-detail__icon--main"><div class="score-rank score-rank--full score-rank--D"></div></div><div class="play-detail__detail"><a class="play-detail__title u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/732222#fruits/1546890">L'Oiseau bleu <small class="play-detail__artist">by Mami Kawada</small></a><div class="play-detail__beatmap-and-time"><span class="play-detail__beatmap"><span class="fal fa-extra-mode-fruits"></span> Cup</span><span class="play-detail__time"><time class="js-timeago" datetime="2019-12-16T07:18:06Z" title="2019-12-16T07:18:06Z">7 years ago</time></span></div></div></div><div class="play-detail__group play-detail__group--bottom"><div class="play-detail__score-detail"><div class="play-detail__icon play-detail__icon--extra"><div class="score-rank score-rank--full score-rank--D"></div></div><div class="play-detail__score-detail-top-right"><div class="play-detail__accuracy-and-weighted-pp"><span class="play-detail__accuracy">39.12%</span><span class="play-detail__weighted-pp u-hover"><span title="0">0pp</span></span></div></div></div><div class="play-detail__mods-pp"><div class="play-detail__mods"><div class="mod mod--type-DifficultyReduction" title="No Fail"><div class="mod__icon mod__icon--NF" data-acronym="NF"></div></div><div class="mod mod--type-Conversion" title="Classic"><div class="mod__icon mod__icon--CL" data-acronym="CL"></div></div></div><div class="play-detail__pp play-detail__pp--watch-count"><span><small><span class="fas fa-eye"></span></small> 4</span></div></div><div class="play-detail__more"><button class="popup-menu" type="button"><span class="fas fa-ellipsis-v"></span></button></div></div></div><div class="play-detail"><a class="play-detail__bg-link" href="https://osu.ppy.sh/scores/521964"></a><div class="play-detail__group play-detail__group--top"><div class="play-detail__icon play-detail__icon--main"><div class="score-rank score-rank--full score-rank--A"></div></div><div class="play-detail__detail"><a class="play-detail__title u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/2459#osu/19753">Ryuuseigun <small class="play-detail__artist">by Nico Nico Douga</small></a><div class="play-detail__beatmap-and-time"><span class="play-detail__beatmap"><span class="fal fa-extra-mode-osu"></span> Marathon</span><span class="play-detail__time"><time class="js-timeago" datetime="2008-11-17T20:36:21Z" title="2008-11-17T20:36:21Z">18 years ago</time></span></div></div></div><div class="play-detail__group play-detail__group--bottom"><div class="play-detail__score-detail"><div class="play-detail__icon play-detail__icon--extra"><div class="score-rank score-rank--full score-rank--A"></div></div><div class="play-detail__score-detail-top-right"><div class="play-detail__accuracy-and-weighted-pp"><span class="play-detail__accuracy">91.03%</span><span class="play-detail__weighted-pp u-hover"><span title="19.561">20pp</span></span></div></div></div><div class="play-detail__mods-pp"><div class="play-detail__mods"><div class="mod mod--type-Conversion" title="Classic"><div class="mod__icon mod__icon--CL" data-acronym="CL"></div></div></div><div class="play-detail__pp play-detail__pp--watch-count"><span><small><span class="fas fa-eye"></span></small> 3</span></div></div><div class="play-detail__more"><button class="popup-menu" type="button"><span class="fas fa-ellipsis-v"></span></button></div></div></div><div class="play-detail"><a class="play-detail__bg-link" href="https://osu.ppy.sh/scores/100138"></a><div class="play-detail__group play-detail__group--top"><div class="play-detail__icon play-detail__icon--main"><div class="score-rank score-rank--full score-rank--A"></div></div><div class="play-detail__detail"><a class="play-detail__title u-ellipsis-overflow" href="https://osu.ppy.sh/beatmapsets/617#osu/3762">Still Alive (Raddox Remix) <small class="play-detail__artist">by Raddox</small></a><div class="play-detail__beatmap-and-time"><span class="play-detail__beatmap"><span class="fal fa-extra-mode-osu"></span> Cruisin'</span><span class="play-detail__time"><time class="js-timeago" datetime="2008-04-17T03:30:10Z" title="2008-04-17T03:30:10Z">18 years ago</time></span></div></div></div><div class="play-detail__group play-detail__group--bottom"><div class="play-detail__score-detail"><div class="play-detail__icon play-detail__icon--extra"><div class="score-rank score-rank--full score-rank--A"></div></div><div class="play-detail__score-detail-top-right"><div class="play-detail__accuracy-and-weighted-pp"><span class="play-detail__accuracy">94.95%</span><span class="play-detail__weighted-pp u-hover"><span title="10.714">11pp</span></span></div></div></div><div class="play-detail__mods-pp"><div class="play-detail__mods"><div class="mod mod--type-Conversion" title="Classic"><div class="mod__icon mod__icon--CL" data-acronym="CL"></div></div></div><div class="play-detail__pp play-detail__pp--watch-count"><span><small><span class="fas fa-eye"></span></small> 2</span></div></div><div class="play-detail__more"><button class="popup-menu" type="button"><span class="fas fa-ellipsis-v"></span></button></div></div></div><button type="button" class="show-more-link show-more-link--profile-page"><span class="show-more-link__spinner"><span class="la-ball-clip-rotate"></span></span><span class="show-more-link__label"><span class="show-more-link__label-icon show-more-link__label-icon--left"><span class="fas fa-angle-down"></span></span><span class="show-more-link__label-text">show more</span><span class="show-more-link__label-icon show-more-link__label-icon--right"><span class="fas fa-angle-down"></span></span></span></button></div></div></div></div><div class="js-sortable--page" data-page-id="kudosu"><div class="page-extra"><div class="u-relative"><h2 class="title title--page-extra">Kudosu!</h2></div><div class="lazy-load lazy-load--loading"><span class="la-ball-clip-rotate"></span></div></div></div><div class="js-sortable--page" data-page-id="top_ranks"><div class="page-extra"><div class="u-relative"><h2 class="title title--page-extra">Scores</h2></div><div class="lazy-load lazy-load--loading"><span class="la-ball-clip-rotate"></span></div></div></div><div class="js-sortable--page" data-page-id="medals"><div class="page-extra"><div class="u-relative"><h2 class="title title--page-extra">Medals</h2></div><div class="page-extra__recent-medals-box"><h3 class="title title--page-extra-small">Latest</h3><div class="page-extra__recent-medals"><div class="badge-achievement badge-achievement--dynamic-height"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-secret-couriercatapult.png 1x, https://assets.ppy.sh/medals/web/all-secret-couriercatapult@2x.png 2x" alt="Courier Catapult" src="https://assets.ppy.sh/medals/web/all-secret-couriercatapult.png"></div><div class="badge-achievement badge-achievement--dynamic-height"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-secret-consolation_prize.png 1x, https://assets.ppy.sh/medals/web/all-secret-consolation_prize@2x.png 2x" alt="Consolation Prize" src="https://assets.ppy.sh/medals/web/all-secret-consolation_prize.png"></div><div class="badge-achievement badge-achievement--dynamic-height"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-skill-dc-1.png 1x, https://assets.ppy.sh/medals/web/all-skill-dc-1@2x.png 2x" alt="Daily Sprout" src="https://assets.ppy.sh/medals/web/all-skill-dc-1.png"></div><div class="badge-achievement badge-achievement--dynamic-height"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-secret-identity.png 1x, https://assets.ppy.sh/medals/web/all-secret-identity@2x.png 2x" alt="Value Your Identity" src="https://assets.ppy.sh/medals/web/all-secret-identity.png"></div><div class="badge-achievement badge-achievement--dynamic-height"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/osu-secret-overconfident.png 1x, https://assets.ppy.sh/medals/web/osu-secret-overconfident@2x.png 2x" alt="Overconfident" src="https://assets.ppy.sh/medals/web/osu-secret-overconfident.png"></div><div class="badge-achievement badge-achievement--dynamic-height"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-intro-hidden.png 1x, https://assets.ppy.sh/medals/web/all-intro-hidden@2x.png 2x" alt="Blindsight" src="https://assets.ppy.sh/medals/web/all-intro-hidden.png"></div><div class="badge-achievement badge-achievement--dynamic-height"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/osu-skill-fc-1.png 1x, https://assets.ppy.sh/medals/web/osu-skill-fc-1@2x.png 2x" alt="Totality" src="https://assets.ppy.sh/medals/web/osu-skill-fc-1.png"></div><div class="badge-achievement badge-achievement--dynamic-height"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/osu-skill-pass-1.png 1x, https://assets.ppy.sh/medals/web/osu-skill-pass-1@2x.png 2x" alt="Rising Star" src="https://assets.ppy.sh/medals/web/osu-skill-pass-1.png"></div></div></div><div class="medals-group"><div class="medals-group__group"><h3 class="medals-group__title">Hush-Hush</h3><div class="medals-group__medals"><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-secret-consolation_prize.png 1x, https://assets.ppy.sh/medals/web/all-secret-consolation_prize@2x.png 2x" alt="Consolation Prize" src="https://assets.ppy.sh/medals/web/all-secret-consolation_prize.png"></div><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-secret-challenge_accepted.png 1x, https://assets.ppy.sh/medals/web/all-secret-challenge_accepted@2x.png 2x" alt="Challenge Accepted" src="https://assets.ppy.sh/medals/web/all-secret-challenge_accepted.png"></div><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-secret-quick_draw.png 1x, https://assets.ppy.sh/medals/web/all-secret-quick_draw@2x.png 2x" alt="Quick Draw" src="https://assets.ppy.sh/medals/web/all-secret-quick_draw.png"></div><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-secret-identity.png 1x, https://assets.ppy.sh/medals/web/all-secret-identity@2x.png 2x" alt="Value Your Identity" src="https://assets.ppy.sh/medals/web/all-secret-identity.png"></div><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-secret-couriercatapult.png 1x, https://assets.ppy.sh/medals/web/all-secret-couriercatapult@2x.png 2x" alt="Courier Catapult" src="https://assets.ppy.sh/medals/web/all-secret-couriercatapult.png"></div></div></div><div class="medals-group__group"><h3 class="medals-group__title">Hush-Hush (Expert)</h3><div class="medals-group__medals"><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-secret-perseverance.png 1x, https://assets.ppy.sh/medals/web/all-secret-perseverance@2x.png 2x" alt="Perseverance" src="https://assets.ppy.sh/medals/web/all-secret-perseverance.png"></div><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/osu-secret-overconfident.png 1x, https://assets.ppy.sh/medals/web/osu-secret-overconfident@2x.png 2x" alt="Overconfident" src="https://assets.ppy.sh/medals/web/osu-secret-overconfident.png"></div></div></div><div class="medals-group__group"><h3 class="medals-group__title">Mod Introduction</h3><div class="medals-group__medals"><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-intro-hidden.png 1x, https://assets.ppy.sh/medals/web/all-intro-hidden@2x.png 2x" alt="Blindsight" src="https://assets.ppy.sh/medals/web/all-intro-hidden.png"></div><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-intro-nofail.png 1x, https://assets.ppy.sh/medals/web/all-intro-nofail@2x.png 2x" alt="Risk Averse" src="https://assets.ppy.sh/medals/web/all-intro-nofail.png"></div><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-intro-halftime.png 1x, https://assets.ppy.sh/medals/web/all-intro-halftime@2x.png 2x" alt="Slowboat" src="https://assets.ppy.sh/medals/web/all-intro-halftime.png"></div></div></div><div class="medals-group__group"><h3 class="medals-group__title">Skill &amp; Dedication</h3><div class="medals-group__medals"><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/osu-combo-500.png 1x, https://assets.ppy.sh/medals/web/osu-combo-500@2x.png 2x" alt="500 Combo" src="https://assets.ppy.sh/medals/web/osu-combo-500.png"></div></div><div class="medals-group__medals"><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/osu-plays-5000.png 1x, https://assets.ppy.sh/medals/web/osu-plays-5000@2x.png 2x" alt="5,000 Plays" src="https://assets.ppy.sh/medals/web/osu-plays-5000.png"></div></div><div class="medals-group__medals"><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/osu-skill-pass-1.png 1x, https://assets.ppy.sh/medals/web/osu-skill-pass-1@2x.png 2x" alt="Rising Star" src="https://assets.ppy.sh/medals/web/osu-skill-pass-1.png"></div><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/osu-skill-pass-2.png 1x, https://assets.ppy.sh/medals/web/osu-skill-pass-2@2x.png 2x" alt="Constellation Prize" src="https://assets.ppy.sh/medals/web/osu-skill-pass-2.png"></div><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/osu-skill-pass-3.png 1x, https://assets.ppy.sh/medals/web/osu-skill-pass-3@2x.png 2x" alt="Building Confidence" src="https://assets.ppy.sh/medals/web/osu-skill-pass-3.png"></div><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/osu-skill-pass-4.png 1x, https://assets.ppy.sh/medals/web/osu-skill-pass-4@2x.png 2x" alt="Insanity Approaches" src="https://assets.ppy.sh/medals/web/osu-skill-pass-4.png"></div></div><div class="medals-group__medals"><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/osu-skill-fc-1.png 1x, https://assets.ppy.sh/medals/web/osu-skill-fc-1@2x.png 2x" alt="Totality" src="https://assets.ppy.sh/medals/web/osu-skill-fc-1.png"></div><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/osu-skill-fc-2.png 1x, https://assets.ppy.sh/medals/web/osu-skill-fc-2@2x.png 2x" alt="Business As Usual" src="https://assets.ppy.sh/medals/web/osu-skill-fc-2.png"></div></div><div class="medals-group__medals"><div class="badge-achievement badge-achievement--listing"><img class="badge-achievement__image" srcset="https://assets.ppy.sh/medals/web/all-skill-dc-1.png 1x, https://assets.ppy.sh/medals/web/all-skill-dc-1@2x.png 2x" alt="Daily Sprout" src="https://assets.ppy.sh/medals/web/all-skill-dc-1.png"></div></div></div></div></div></div></div></div></div></div></div>
        </div>
    """

    info = extract(html)
    assert info.get('uid') == '2'
    assert info.get('username') == 'peppy'
    assert info.get('image') == 'https://a.ppy.sh/2?1657169614.png'
    assert info.get('image_bg') == 'https://assets.ppy.sh/user-profile-covers/2/baba245ef60834b769694178f8f6d4f6166c5188c740de084656ad2b80f1eea7.jpeg'
    assert info.get('website') is None
    assert info.get('occupation') is None
    assert info.get('interests') is None
    assert info.get('country') == 'Australia'
    assert info.get('country_code') == 'AU'
    assert info.get('location') is None
    assert info.get('created_at') == '2007-08-28T03:09:12+00:00'
    assert info.get('latest_activity_at') == '2026-07-30T02:49:01+00:00'
    assert info.get('follower_count') == '59754'
    assert info.get('posts_count') == '18226'
    assert info.get('comments_count') == '2981'
    assert info.get('is_deleted') == 'False'
    assert info.get('is_employee') == 'True'
    assert info.get('social_links') is None


# ---------------------------------------------------------------------------
# ORCID-keyed academic platforms (ORCID, OpenAlex, arXiv, DBLP, Scholia)
# ---------------------------------------------------------------------------

def test_orcid_api_extracts_profile_and_affiliations():
    """ORCID public API (pub.orcid.org v3): JSON response with `orcid-identifier`
    + `activities-summary` exposes orcid id, name, bio, researcher URLs, keywords,
    country, current employer/role, education school/degree, works count.
    """
    payload = {
        'orcid-identifier': {'path': '0000-0002-9322-3515', 'host': 'orcid.org'},
        'history': {
            'submission-date': {'value': 1407175067347},
            'verified-primary-email': True,
        },
        'person': {
            'name': {
                'given-names': {'value': 'Yoshua'},
                'family-name': {'value': 'Bengio'},
                'credit-name': None,
            },
            'biography': {'content': 'Bio line.'},
            'researcher-urls': {'researcher-url': [
                {'url': {'value': 'http://www.iro.umontreal.ca/~bengioy'}},
            ]},
            'keywords': {'keyword': [{'content': 'deep learning'}, {'content': 'causality'}]},
            'addresses': {'address': [{'country': {'value': 'CA'}}]},
            'emails': {'email': []},
            'other-names': {'other-name': []},
            'external-identifiers': {'external-identifier': [
                {'external-id-type': 'Scopus Author ID', 'external-id-value': '7003958103'},
            ]},
        },
        'activities-summary': {
            'employments': {'affiliation-group': [{'summaries': [{'employment-summary': {
                'organization': {'name': 'Université de Montréal'},
                'role-title': 'Professeur titulaire',
            }}]}]},
            'educations': {'affiliation-group': [{'summaries': [{'education-summary': {
                'organization': {'name': 'McGill University'},
                'role-title': 'PhD',
            }}]}]},
            'works': {'group': [{}, {}, {}]},
        },
    }
    info = extract(json.dumps(payload))
    assert info.get('_extractor') == 'ORCID API'
    assert info.get('orcid') == '0000-0002-9322-3515'
    assert info.get('fullname') == 'Yoshua Bengio'
    assert info.get('bio') == 'Bio line.'
    assert info.get('links') == "['http://www.iro.umontreal.ca/~bengioy']"
    assert info.get('interests') == 'deep learning, causality'
    assert info.get('country_code') == 'CA'
    assert info.get('company') == 'Université de Montréal'
    assert info.get('occupation') == 'Professeur titulaire'
    assert info.get('education_school') == 'McGill University'
    assert info.get('education_degree') == 'PhD'
    assert info.get('posts_count') == '3'
    assert info.get('is_verified') == 'True'
    assert info.get('created_at') == '1407175067347'
    assert "'Scopus Author ID': '7003958103'" in info.get('external_ids', '')


def test_openalex_authors_api_maps_metrics_and_topics():
    """OpenAlex Authors API: `works_count` + `cited_by_count` + `summary_stats`
    flags, mapped to standard fields (posts_count, h_index, ...). ORCID and
    OpenAlex IDs have URL prefixes stripped.
    """
    payload = {
        'id': 'https://openalex.org/A5086198262',
        'orcid': 'https://orcid.org/0000-0002-9322-3515',
        'display_name': 'Yoshua Bengio',
        'display_name_alternatives': ['Y. Bengio', 'Bengio Y.'],
        'works_count': 1279,
        'cited_by_count': 452107,
        'summary_stats': {'h_index': 183, 'i10_index': 709},
        'last_known_institutions': [
            {'display_name': 'Mila', 'country_code': 'CA'},
            {'display_name': 'Université de Montréal', 'country_code': 'CA'},
        ],
        'topics': [
            {'display_name': 'Neural Networks'},
            {'display_name': 'Topic Modeling'},
        ],
        'created_date': '2016-06-24T00:00:00',
        'updated_date': '2026-05-25T12:27:37',
    }
    info = extract(json.dumps(payload))
    assert info.get('_extractor') == 'OpenAlex Authors API'
    assert info.get('orcid') == '0000-0002-9322-3515'
    assert info.get('openalex_id') == 'A5086198262'
    assert info.get('fullname') == 'Yoshua Bengio'
    assert info.get('posts_count') == '1279'
    assert info.get('cited_by_count') == '452107'
    assert info.get('h_index') == '183'
    assert info.get('i10_index') == '709'
    assert info.get('company') == 'Mila'
    assert info.get('country_code') == 'CA'
    assert info.get('institutions') == "['Mila', 'Université de Montréal']"
    assert info.get('interests') == 'Neural Networks, Topic Modeling'


def test_arxiv_author_page_extracts_fullname_and_paper_ids():
    """arXiv author page: `<h1>X's articles on arXiv</h1>` + `/abs/<id>` links."""
    html = (
        '<!DOCTYPE html><html><head><title>X</title></head><body>'
        '<h1 class="arxiv-logo">logo</h1>'
        "<h1>Yoshua Bengio's articles on arXiv</h1>"
        '<dl>'
        '<dt><a href="/abs/2305.14594">arXiv:2305.14594</a></dt>'
        '<dt><a href="/abs/2310.04925">arXiv:2310.04925</a></dt>'
        '<dt><a href="/abs/2305.14594">duplicate</a></dt>'
        '</dl></body></html>'
    )
    info = extract(html)
    assert info.get('_extractor') == 'arXiv author page'
    assert info.get('fullname') == 'Yoshua Bengio'
    assert info.get('arxiv_ids') == "['2305.14594', '2310.04925']"
    assert info.get('posts_count') == '2'


def test_dblp_person_record_xml_extracts_pid_affiliation_awards_links():
    """DBLP XML person record: `<dblpperson name pid n>` + `<note type="affiliation">`
    + `<note type="award">` + `<url>` (only those inside the `<person>` wrapper, not
    the `<r>` per-publication URLs).
    """
    xml = (
        '<?xml version="1.0"?>'
        '<dblpperson name="Yoshua Bengio" pid="56/953" n="1236">'
        '<person key="homepages/56/953">'
        '<author pid="56/953">Yoshua Bengio</author>'
        '<note type="affiliation">University of Montréal, Department of Computer Science</note>'
        '<note label="2018" type="award">Turing Award</note>'
        '<url>https://mila.quebec/en/yoshua-bengio/</url>'
        '<url>https://orcid.org/0000-0002-9322-3515</url>'
        '</person>'
        '<r><article key="x"><url>https://example.com/paper.pdf</url></article></r>'
        '</dblpperson>'
    )
    info = extract(xml)
    assert info.get('_extractor') == 'DBLP person record'
    assert info.get('fullname') == 'Yoshua Bengio'
    assert info.get('dblp_pid') == '56/953'
    assert info.get('posts_count') == '1236'
    assert 'University of Montréal' in info.get('company', '')
    assert info.get('awards') == "['2018: Turing Award']"
    # Per-publication URL must NOT leak into `links`.
    assert info.get('links') == "['https://mila.quebec/en/yoshua-bengio/', 'https://orcid.org/0000-0002-9322-3515']"


def test_scholia_canonical_link_yields_wikidata_qid():
    """Scholia author page: canonical link exposes Wikidata QID; the rest of
    the page is JS-rendered, so QID is the only durable signal.
    """
    html = (
        '<!DOCTYPE html><html><head>'
        '<title>Scholia</title>'
        '<link rel="canonical" href="https://scholia.toolforge.org/author/Q3572699">'
        '</head><body><h1 id="h1">Author</h1></body></html>'
    )
    info = extract(html)
    assert info.get('_extractor') == 'Scholia author profile'
    assert info.get('wikidata_qid') == 'Q3572699'


def test_orcid_url_mutations_target_five_platforms():
    """A bare orcid.org/{id} URL fans out into the 5 ORCID-keyed endpoints."""
    from socid_extractor.main import mutate_url
    results = mutate_url('https://orcid.org/0000-0002-9322-3515')
    urls = {u for u, _hdrs in results}
    assert 'https://pub.orcid.org/v3.0/0000-0002-9322-3515/record' in urls
    assert 'https://api.openalex.org/authors/orcid:0000-0002-9322-3515' in urls
    assert 'https://arxiv.org/a/0000-0002-9322-3515' in urls
    assert 'https://dblp.org/orcid/0000-0002-9322-3515.xml' in urls
    assert 'https://scholia.toolforge.org/orcid/0000-0002-9322-3515' in urls
    # ORCID API mutation must carry the Accept: application/json header
    # (default content-negotiation returns XML).
    orcid_api = next((h for u, h in results if u.endswith('/v3.0/0000-0002-9322-3515/record')), None)
    assert orcid_api == {'Accept': 'application/json'}


# ---------------------------------------------------------------------------
# Structural / meta tests
# ---------------------------------------------------------------------------

def test_no_flag_subset_shadows():
    """Detect scheme pairs where one's flags are a subset of another's.

    If scheme A's flags ⊂ scheme B's flags and A appears *before* B in the
    dict, then B can never match because A always wins.  This test ensures
    every pair where one is a strict subset is ordered correctly (more specific
    first).
    """
    names = list(schemes.keys())
    for i, name_a in enumerate(names):
        flags_a = set(schemes[name_a]['flags'])
        for j, name_b in enumerate(names):
            if i == j:
                continue
            flags_b = set(schemes[name_b]['flags'])
            if flags_a < flags_b and i > j:
                # A has strictly fewer flags than B but comes AFTER B
                # This means the more specific B can never be reached
                # because less specific A matches first — that's fine.
                # The problem is the REVERSE: less specific before more specific.
                pass
            if flags_b < flags_a and i < j:
                # A (earlier) has MORE flags (more specific) than B (later) — correct order
                pass
            if flags_a < flags_b and i < j:
                # A (earlier) is LESS specific than B (later) — B is shadowed!
                raise AssertionError(
                    f'Scheme "{name_a}" (pos {i}, flags={flags_a}) shadows '
                    f'"{name_b}" (pos {j}, flags={flags_b}) because its flags '
                    f'are a strict subset and it appears earlier. '
                    f'Move "{name_b}" before "{name_a}".'
                )


def test_safe_deep_get():
    """Verify safe_deep_get traverses nested structures without raising."""
    data = {'a': {'b': [{'c': 42}]}}
    assert safe_deep_get(data, 'a', 'b', 0, 'c') == 42
    assert safe_deep_get(data, 'a', 'x') is None
    assert safe_deep_get(data, 'a', 'b', 99) is None
    assert safe_deep_get(None, 'a') is None
    assert safe_deep_get(data, 'a', 'b', 0, 'c', default='fallback') == 42
    assert safe_deep_get(data, 'z', default='fallback') == 'fallback'


def test_extract_next_data_helper():
    """Verify extract_next_data parses __NEXT_DATA__ from HTML."""
    html = '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"x":1}}}</script>'
    result = extract_next_data(html)
    assert result == {"props": {"pageProps": {"x": 1}}}
    assert extract_next_data('no script here') == {}
    assert extract_next_data('') == {}


def test_next_data_page_props_helper():
    """Verify next_data_page_props extracts nested pageProps subkeys."""
    data = {"props": {"pageProps": {"user": {"name": "Alice"}}}}
    html = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + '</script>'
    result = json.loads(next_data_page_props(html, 'user'))
    assert result == {"name": "Alice"}
    # Missing key returns empty dict serialized
    result2 = json.loads(next_data_page_props(html, 'nonexistent'))
    assert result2 == {}


def test_youtube_ytinitialdata():
    """YouTube ytInitialData: extract channel metadata from embedded JSON."""
    yt_data = {
        "metadata": {
            "channelMetadataRenderer": {
                "title": "Google",
                "externalId": "UCK8sQmJBp8GCxrOtXWBpyEA",
                "description": "Official Google channel",
                "vanityChannelUrl": "http://www.youtube.com/@Google",
                "avatar": {"thumbnails": [{"url": "https://yt3.googleusercontent.com/avatar.jpg"}]},
                "keywords": "Google Technology",
                "isFamilySafe": True,
                "facebookProfileId": "Google",
            }
        }
    }
    html = (
        '<!DOCTYPE html><html><head></head><body>'
        '<script>var ytInitialData = '
        + json.dumps(yt_data)
        + ';</script><script>var ytInitialPlayerResponse = {};</script>'
        '<div>channelMetadataRenderer present</div>'
        '</body></html>'
    )
    info = extract(html)
    assert info.get('youtube_channel_id') == 'UCK8sQmJBp8GCxrOtXWBpyEA'
    assert info.get('fullname') == 'Google'
    assert info.get('bio') == 'Official Google channel'
    assert 'yt3.googleusercontent.com' in info.get('image', '')
    assert info.get('channel_url') == 'http://www.youtube.com/@Google'
    assert info.get('keywords') == 'Google Technology'
    assert info.get('is_family_safe') == 'True'
    # 'Google' is a username, not a numeric ID
    assert info.get('facebook_username') == 'Google'
    assert 'facebook_id' not in info


def test_lesswrong_graphql_api():
    """Lesswrong GraphQL API: extract user profile from GQL response."""
    body = json.dumps({
        "data": {
            "user": {
                "result": {
                    "displayName": "Eliezer Yudkowsky",
                    "slug": "eliezer_yudkowsky",
                    "karma": 159624,
                    "createdAt": "2009-02-23T21:58:56.739Z",
                    "bio": "",
                }
            }
        }
    })
    info = extract(body)
    assert info.get('fullname') == 'Eliezer Yudkowsky'
    assert info.get('username') == 'eliezer_yudkowsky'
    assert info.get('karma') == '159624'
    assert info.get('created_at') == '2009-02-23T21:58:56.739Z'


def test_lesswrong_graphql_null_user():
    """Lesswrong GraphQL API: null user returns empty."""
    body = json.dumps({
        "data": {"user": None}
    })
    # Should not match — no "slug" or "karma" flags
    info = extract(body)
    assert not info.get('fullname')


def test_weibo_api_extracts_profile_fields():
    """Verifies the Weibo API scheme extracts user profile fields from JSON response."""
    body = json.dumps({
        "ok": 1,
        "data": {
            "user": {
                "id": 1733299783,
                "idstr": "1733299783",
                "screen_name": "郭靜Claire",
                "profile_image_url": "https://tvax2.sinaimg.cn/crop.0.0.1080.1080.50/67500e47ly8hape352btfj20u00u0mz1.jpg",
                "profile_url": "/u/1733299783",
                "verified": True,
                "verified_type": 0,
                "domain": "clairekuo",
                "avatar_large": "https://tvax2.sinaimg.cn/crop.0.0.1080.1080.180/67500e47ly8hape352btfj20u00u0mz1.jpg",
                "avatar_hd": "https://tvax2.sinaimg.cn/crop.0.0.1080.1080.1024/67500e47ly8hape352btfj20u00u0mz1.jpg",
                "verified_reason": "台湾女歌手",
                "description": "歌手郭静",
                "location": "台湾 台北市",
                "gender": "f",
                "followers_count": 3126727,
                "friends_count": 217,
                "statuses_count": 2248,
            }
        }
    }, separators=(',', ':'))
    info = extract(body)
    assert info.get('weibo_id') == '1733299783'
    assert info.get('username') == 'clairekuo'
    assert info.get('fullname') == '郭靜Claire'
    assert info.get('bio') == '歌手郭静'
    assert info.get('image') == 'https://tvax2.sinaimg.cn/crop.0.0.1080.1080.1024/67500e47ly8hape352btfj20u00u0mz1.jpg'
    assert info.get('gender') == 'f'
    assert info.get('location') == '台湾 台北市'
    assert info.get('verified') == 'True'
    assert info.get('verified_reason') == '台湾女歌手'
    assert info.get('follower_count') == '3126727'
    assert info.get('following_count') == '217'
    assert info.get('statuses_count') == '2248'


def test_weibo_api_url_mutations():
    """Verifies Weibo API url_mutations convert profile URLs to API endpoints."""
    from socid_extractor.main import mutate_url

    # Username URL pattern
    results = mutate_url('https://weibo.com/clairekuo')
    urls = [r[0] for r in results]
    assert 'https://weibo.com/ajax/profile/info?custom=clairekuo' in urls

    # User ID URL pattern
    results = mutate_url('https://weibo.com/u/6215884155')
    urls = [r[0] for r in results]
    assert 'https://weibo.com/ajax/profile/info?uid=6215884155' in urls


def test_picsart_facebook_uid_from_image():
    """Picsart: extract facebook_uid from graph.facebook.com avatar URL."""
    body = json.dumps({
        "id": 12345,
        "username": "testuser",
        "name": "Test User",
        "photo": "https://graph.facebook.com/231008367325211/picture?type=normal",
        "status_message": "Hello",
        "followers_count": 10,
        "following_count": 5,
        "likes_count": 100,
        "photos_count": 50,
        "is_verified": False,
        "remix_score": 0,
        "dashboard_visibility": True,
    })
    info = extract(body)
    assert info.get('facebook_uid') == '231008367325211'
    assert info.get('picsart_id') == '12345'


def test_picsart_no_facebook_uid_for_regular_avatar():
    """Picsart: no facebook_uid when avatar is not from graph.facebook.com."""
    body = json.dumps({
        "id": 99,
        "username": "other",
        "name": "Other",
        "photo": "https://cdn.picsart.com/avatars/photo.jpg",
        "remix_score": 0,
        "dashboard_visibility": True,
    })
    info = extract(body)
    assert not info.get('facebook_uid')
    assert info.get('picsart_id') == '99'


def test_habr_og_profile():
    """Habr: extract fullname and username from og:title meta tag."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:site_name" content="Хабр">'
        '<meta property="og:title" content="Олег Бунин aka olegbunin\n     - ">'
        '<meta property="og:url" content="https://habr.com/ru/users/olegbunin/">'
        '</head><body></body></html>'
    )
    info = extract(html)
    assert info.get('fullname') == 'Олег Бунин'
    assert info.get('username') == 'olegbunin'
    assert 'habr.com' in info.get('website', '')


def test_product_hunt_og_profile():
    """Product Hunt: extract twitter_username and username from meta tags."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:site_name" content="Product Hunt">'
        '<meta property="og:type" content="profile">'
        '<meta name="twitter:creator" content="@rrhoover">'
        '<meta property="og:url" content="https://www.producthunt.com/@rrhoover">'
        '</head><body></body></html>'
    )
    info = extract(html)
    assert info.get('twitter_username') == 'rrhoover'
    assert info.get('username') == 'rrhoover'


def test_taplink_og_profile():
    """Taplink: extract username, fullname and avatar from og:meta tags."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:image" content="https://taplink.st/a/0/5/e/e/c325e9.jpg?1">'
        '<meta property="og:type" content=website />'
        '<meta property="og:title" content="Selenagomez at Taplink"/>'
        '<meta property="og:url" content="https://taplink.cc/selenagomez"/>'
        '<meta property="og:site_name" content="Taplink"/>'
        '</head><body></body></html>'
    )
    info = extract(html)
    assert info.get('fullname') == 'Selenagomez'
    assert info.get('username') == 'selenagomez'
    assert 'taplink.st' in info.get('image', '')


def test_taplink_nonexistent_user_not_matched():
    """Taplink: homepage (redirect for non-existent user) should NOT match."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:title" content="Taplink - landing page that drives your sales on Instagram">'
        '<meta property="og:url" content="https://taplink.at/en/">'
        '<meta property="og:site_name" content="Taplink">'
        '</head><body></body></html>'
    )
    info = extract(html)
    # Should not match Taplink scheme — no "at Taplink" in og:title
    assert not info.get('username')


def test_chess_com_html_profile():
    """Chess.com HTML: extract fullname, username and image from og:meta."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:title" content="John (John) - Chess Profile">'
        '<meta property="og:url" content="https://www.chess.com/member/john">'
        '<meta property="og:site_name" content="Chess.com">'
        '<meta property="og:image" content="https://www.chess.com/share/user/john">'
        '</head><body></body></html>'
    )
    info = extract(html)
    assert info.get('fullname') == 'John'
    assert info.get('username') == 'John'
    assert info.get('image') == 'https://www.chess.com/share/user/john'


def test_roblox_html_profile():
    """Roblox HTML: extract username, uid and avatar from og:meta after redirect."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:site_name" content="Roblox">'
        '<meta property="og:title" content="john&#x27;s Profile">'
        '<meta property="og:type" content="profile">'
        '<meta property="og:url" content="https://www.roblox.com/users/2191/profile">'
        '<meta property="og:image" content="https://tr.rbxcdn.com/30DAY-Avatar-A852E46C43BF1A5E01BD1FDA883FD398-Png/352/352/Avatar/Png/noFilter">'
        '</head><body></body></html>'
    )
    info = extract(html)
    assert info.get('username') == 'john'
    assert info.get('uid') == '2191'
    assert 'rbxcdn.com' in info.get('image', '')


def test_stack_exchange_api_json():
    """Stack Exchange API: extract user profile from /users?inname= JSON response."""
    body = json.dumps({
        "items": [{
            "account_id": 21543594,
            "reputation": 1,
            "user_id": 15880884,
            "user_type": "registered",
            "link": "https://stackoverflow.com/users/15880884/soxoj1",
            "profile_image": "https://www.gravatar.com/avatar/86d899547a5fce05b6a63e540878c69f",
            "display_name": "Soxoj1",
            "creation_date": 1620592473,
        }],
        "has_more": False,
    })
    info = extract(body)
    assert info.get('uid') == '15880884'
    assert info.get('account_id') == '21543594'
    assert info.get('username') == 'Soxoj1'
    assert 'gravatar.com' in info.get('image', '')
    assert info.get('reputation') == '1'
    assert info.get('link') == 'https://stackoverflow.com/users/15880884/soxoj1'
    assert info.get('created_at') == '1620592473'


def test_stack_exchange_api_empty_items():
    """Stack Exchange API: empty items array should not match."""
    body = json.dumps({"items": [], "has_more": False})
    info = extract(body)
    assert not info.get('uid')


def test_leetcode_graphql_api_json():
    """LeetCode GraphQL: extract user profile from matchedUser response."""
    body = json.dumps({
        "data": {
            "matchedUser": {
                "username": "soxoj",
                "profile": {
                    "realName": "Soxoj",
                    "aboutMe": "OSINT researcher",
                    "userAvatar": "https://assets.leetcode.com/users/soxoj/avatar_1561894548.png",
                    "countryName": "Russia",
                    "company": "Anthropic",
                    "school": "MIT",
                    "ranking": 5000001,
                },
            }
        }
    })
    info = extract(body)
    assert info.get('username') == 'soxoj'
    assert info.get('fullname') == 'Soxoj'
    assert info.get('bio') == 'OSINT researcher'
    assert 'leetcode.com' in info.get('image', '')
    assert info.get('country') == 'Russia'
    assert info.get('company') == 'Anthropic'
    assert info.get('school') == 'MIT'
    assert info.get('ranking') == '5000001'


def test_leetcode_graphql_empty_profile():
    """LeetCode GraphQL: empty realName/aboutMe should return None, not empty string."""
    body = json.dumps({
        "data": {
            "matchedUser": {
                "username": "emptyuser",
                "profile": {
                    "realName": "",
                    "aboutMe": "",
                    "userAvatar": "https://assets.leetcode.com/users/default.png",
                    "countryName": None,
                    "company": None,
                    "school": None,
                    "ranking": 999999,
                },
            }
        }
    })
    info = extract(body)
    assert info.get('username') == 'emptyuser'
    assert not info.get('fullname')
    assert not info.get('bio')
    assert not info.get('country')
    assert not info.get('company')


def test_boosty_api_json():
    """Boosty API: extract blog owner profile with telegram crosslink."""
    body = json.dumps({
        "id": 123,
        "title": "Организуем митапы",
        "description": [
            {"type": "text", "content": '["Канал про митапы","unstyled",[]]', "modificator": ""},
            {"type": "text", "content": "", "modificator": "BLOCK_END"},
        ],
        "owner": {
            "name": "OSINT mindset",
            "id": 10276482,
            "avatarUrl": "https://images.boosty.to/user/10276482/avatar",
            "externalApps": {
                "telegram": {"username": "soxoj", "hasAccount": True},
            },
        },
        "signedQuery": "abc123",
    })
    info = extract(body)
    assert info.get('uid') == '10276482'
    assert info.get('fullname') == 'OSINT mindset'
    assert 'boosty.to' in info.get('image', '')
    assert info.get('blog_title') == 'Организуем митапы'
    assert info.get('blog_description') == 'Канал про митапы'
    assert info.get('telegram_username') == 'soxoj'


def test_boosty_api_no_telegram():
    """Boosty API: missing telegram should return None, not crash."""
    body = json.dumps({
        "id": 456,
        "title": "Some Blog",
        "description": "",
        "owner": {
            "name": "Author",
            "id": 999,
            "avatarUrl": "https://images.boosty.to/user/999/avatar",
            "externalApps": {},
        },
        "signedQuery": "xyz",
    })
    info = extract(body)
    assert info.get('uid') == '999'
    assert info.get('fullname') == 'Author'
    assert not info.get('telegram_username')


def test_facebook_user_profile_meta_tags():
    """
    Verifies the **Facebook user profile** scheme extracts data from OG and app-link
    meta tags (the format served to crawlers by Facebook).

    **Check:** `uid`, `username`, `fullname`, `description`, and `image` are extracted
    from the meta tags in the HTML fixture.
    """
    html = (
        '<!DOCTYPE html>'
        '<html id="facebook" class="_9dls" lang="en" dir="ltr"><head>'
        '<title>Mark Zuckerberg</title>'
        '<meta property="al:android:app_name" content="Facebook" />'
        '<meta property="al:android:url" content="fb://profile/4" />'
        '<meta property="og:title" content="Mark Zuckerberg" />'
        '<meta property="og:description" content="Mark Zuckerberg. 121,000,000 likes" />'
        '<meta property="og:url" content="https://www.facebook.com/zuck/" />'
        '<meta property="og:image" content="https://lookaside.fbsbx.com/lookaside/crawler/media/?media_id=4" />'
        '</head><body></body></html>'
    )
    info = extract(html)
    assert info.get('uid') == '4'
    assert info.get('username') == 'zuck'
    assert info.get('fullname') == 'Mark Zuckerberg'
    assert 'likes' in info.get('description', '')
    assert 'lookaside' in info.get('image', '')


def test_facebook_user_profile_no_match_without_og_title():
    """
    Verifies the **Facebook user profile** scheme does NOT match pages that lack
    ``og:title`` meta tag (e.g. login/error pages).
    """
    html = (
        '<!DOCTYPE html>'
        '<html id="facebook" lang="en"><head>'
        '<title>Error</title>'
        '</head><body><h1>Sorry, something went wrong.</h1></body></html>'
    )
    info = extract(html)
    assert not info.get('uid')
    assert not info.get('fullname')


def test_smule_profile_extraction():
    """
    Verifies the **Smule** scheme extracts user data from the inline
    ``Profile: {"user": ...}`` JSON block found in Smule profile pages.
    """
    user_data = {
        "user": {
            "account_id": 173,
            "handle": "Blue",
            "pic_url": "https://c-sf.smule.com/rs-z0/account/icon/v4_defpic.png",
            "url": "/Blue",
            "followers": "155",
            "followees": "0",
            "num_performances": "0",
            "is_following": False,
        }
    }
    html = (
        '<!DOCTYPE html><html><head>'
        '<title>Blue on Smule</title>'
        '</head><body>'
        '<script>smule.com Profile: ' + json.dumps(user_data) + '\n</script>'
        '</body></html>'
    )
    info = extract(html)
    assert info.get('uid') == '173'
    assert info.get('username') == 'Blue'
    assert info.get('image') == 'https://c-sf.smule.com/rs-z0/account/icon/v4_defpic.png'
    assert info.get('follower_count') == '155'
    assert info.get('following_count') == '0'


def test_warpcast_api_json():
    """Warpcast API: extract Farcaster profile with connected accounts."""
    body = json.dumps({
        "result": {
            "user": {
                "fid": 3,
                "displayName": "Dan Romero",
                "profile": {
                    "bio": {"text": "Building Farcaster", "mentions": []},
                    "url": "https://danromero.org",
                },
                "followerCount": 345000,
                "followingCount": 77,
                "username": "dwr",
                "pfp": {"url": "https://imagedelivery.net/abc/original", "verified": False},
                "connectedAccounts": [
                    {"connectedAccountId": "123", "platform": "x", "username": "dwr", "expired": False}
                ],
            },
            "collectionsOwned": [],
            "extras": {
                "fid": 3,
                "custodyAddress": "0x6b0bda3f2ffed5efc83fa8c024acff1dd45793f1",
            },
        }
    })
    info = extract(body)
    assert info.get('uid') == '3'
    assert info.get('username') == 'dwr'
    assert info.get('fullname') == 'Dan Romero'
    assert info.get('bio') == 'Building Farcaster'
    assert info.get('url') == 'https://danromero.org'
    assert 'imagedelivery.net' in info.get('image', '')
    assert info.get('follower_count') == '345000'
    assert info.get('following_count') == '77'
    assert info.get('twitter_username') == 'dwr'


def test_warpcast_api_no_connected_accounts():
    """Warpcast API: user with no connected accounts."""
    body = json.dumps({
        "result": {
            "user": {
                "fid": 999,
                "displayName": "Anon",
                "profile": {"bio": {"text": "", "mentions": []}, "url": ""},
                "followerCount": 0,
                "followingCount": 0,
                "username": "anon",
                "pfp": {"url": "https://example.com/avatar.png", "verified": False},
                "connectedAccounts": [],
            },
            "collectionsOwned": [],
            "extras": {"fid": 999},
        }
    })
    info = extract(body)
    assert info.get('uid') == '999'
    assert info.get('username') == 'anon'
    assert info.get('bio') is None
    assert info.get('twitter_username') is None


def test_paragraph_api_json():
    """Paragraph API: extract blog profile with wallet, bio, socials."""
    body = json.dumps({
        "id": "abc123",
        "userId": "user456",
        "name": "ZachXBT",
        "reputation": "MEDIUM_LOW",
        "needToSetup": False,
        "lowercase_url": "@zachxbt",
        "url": "@zachXBT",
        "updatedAt": 1763923578663,
        "latestPostModifiedTs": 1763923734274,
        "social": {"twitter": "zachxbt"},
        "logo_url": None,
        "user": {
            "id": "user456",
            "displayName": {"name": "ZachXBT", "isTruncated": False, "fullName": "ZachXBT"},
            "authorName": "ZachXBT",
            "authorBio": "Scam survivor turned investigator",
            "avatar_url": "https://storage.googleapis.com/papyrus_images/avatar.jpg",
            "social": {"twitter": "zachxbt ", "github": "", "facebook": "", "instagram": ""},
            "wallet_address": "0x23dBf06665155FA55E7944803D43580a73ffa9b0",
        },
    })
    info = extract(body)
    assert info.get('uid') == 'abc123'
    assert info.get('paragraph_user_id') == 'user456'
    assert info.get('fullname') == 'ZachXBT'
    assert info.get('username') == 'zachxbt'
    assert info.get('bio') == 'Scam survivor turned investigator'
    assert 'papyrus_images' in info.get('image', '')
    assert '2025' in info.get('updated_at', '')  # 1763923578663 → datetime string
    assert '2025' in info.get('latest_activity_at', '')  # 1763923734274 → datetime string
    assert info.get('twitter_username') == 'zachxbt'  # trailing space stripped
    assert info.get('github_username') is None  # empty string → None
    assert info.get('facebook_username') is None  # empty string → None
    assert info.get('instagram_username') is None
    assert info.get('wallet_address') == '0x23dBf06665155FA55E7944803D43580a73ffa9b0'


def test_fragment_html():
    """Fragment: extract Telegram username, TON wallet, sale price, and purchase date."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<title>durov – Fragment</title>'
        '<meta property="og:site_name" content="Fragment Auctions">'
        '</head><body>'
        '<div class="table-cell-value tm-value icon-before icon-ton">3</div>'
        '<a href="https://tonviewer.com/EQBsfrfaZbp2AZsMTXjrO5h7SxegzOkMfYkiHq8hEmspNtxl" '
        'class="tm-wallet" target="_blank">EQBs...Ntxl</a>'
        '<div class="tm-datetime"><time datetime="2024-03-17T19:36:21+00:00">17 Mar 2024</time></div>'
        '</body></html>'
    )
    info = extract(html)
    assert info.get('telegram_username') == 'durov'
    assert info.get('ton_wallet') == 'EQBsfrfaZbp2AZsMTXjrO5h7SxegzOkMfYkiHq8hEmspNtxl'
    assert info.get('sale_price') == '3'
    assert info.get('purchased_at') == '2024-03-17T19:36:21+00:00'


def test_tonometerbot_html():
    """Tonometerbot: extract username and stats from OG meta tags."""
    html = (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta property="og:title" content="@jaga1985"/>'
        '<meta property="og:site_name" content="TonometerBot"/>'
        '<meta property="og:description"\n'
        '      content="@jaga1985, Subscribers: 21, NFT\'s: 111 "/>'
        '</head><body></body></html>'
    )
    info = extract(html)
    assert info.get('username') == 'jaga1985'
    assert info.get('subscriber_count') == '21'
    assert info.get('nft_count') == '111'


def test_spatial_next_data():
    """Spatial: extract profile from __NEXT_DATA__ with socialLinks."""
    user_data = {
        "isPrivate": False,
        "userID": "5eceef2dfa7f113e938acf63",
        "username": "rammy",
        "displayName": "Rammy",
        "about": "VR world builder",
        "avatarImageURL": "https://api.avatarsdk.com/avatars/abc/preview/",
        "numFollowers": 51,
        "numFollowing": 64,
        "socialLinks": {
            "usernameDiscord": "rammy.b",
            "usernameTwitter": "rammyvr",
            "usernameInstagram": "",
            "usernameLinkedin": "",
            "usernameTiktok": "",
        },
        "totalSpacesCount": 8,
    }
    next_data = json.dumps({
        "props": {
            "pageProps": {
                "dehydratedState": {
                    "mutations": [],
                    "queries": [{"state": {"data": user_data}}],
                },
                "username": "rammy",
            }
        }
    })
    html = f'<script id="__NEXT_DATA__" type="application/json">{next_data}</script>'
    info = extract(html)
    assert info.get('uid') == '5eceef2dfa7f113e938acf63'
    assert info.get('username') == 'rammy'
    assert info.get('fullname') == 'Rammy'
    assert info.get('bio') == 'VR world builder'
    assert 'avatarsdk.com' in info.get('image', '')
    assert info.get('follower_count') == '51'
    assert info.get('following_count') == '64'
    assert info.get('discord_username') == 'rammy.b'
    assert info.get('twitter_username') == 'rammyvr'
    assert info.get('instagram_username') is None
    assert info.get('tiktok_username') is None


def test_opensea_full_profile():
    """OpenSea: extract profile from ld+json with bio, image, links."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:title" content="Zachxbt - Profile | OpenSea">'
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"ProfilePage","name":"Zachxbt",'
        '"image":"https://i2c.seadn.io/profiles/0x67d890/avatar.jpeg",'
        '"mainEntity":{"@type":"Person","name":"Zachxbt",'
        '"image":"https://i2c.seadn.io/profiles/0x67d890/avatar.jpeg",'
        '"description":"On-chain sleuth",'
        '"url":"https://opensea.io/Zachxbt",'
        '"sameAs":["https://investigations.notion.site/"]}}'
        '</script></head><body></body></html>'
    )
    info = extract(html)
    assert info.get('username') == 'Zachxbt'
    assert info.get('uid') == 'Zachxbt'
    assert info.get('bio') == 'On-chain sleuth'
    assert 'seadn.io' in info.get('image', '')
    assert 'notion.site' in info.get('links', '')


def test_opensea_minimal_profile():
    """OpenSea: profile without bio/image (wallet as uid)."""
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta property="og:title" content="vitalik - Profile | OpenSea">'
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"ProfilePage","name":"vitalik",'
        '"image":"",'
        '"mainEntity":{"@type":"Person","name":"vitalik",'
        '"image":"","description":"",'
        '"url":"https://opensea.io/0xd0770174161c0de87242775e7ef32c733e144ac4"}}'
        '</script></head><body></body></html>'
    )
    info = extract(html)
    assert info.get('username') == 'vitalik'
    assert info.get('uid') == '0xd0770174161c0de87242775e7ef32c733e144ac4'
    assert info.get('bio') is None
    assert info.get('image') is None


def test_hive_blog_full_profile():
    """Hive Blog: extract profile from inline JSON with stats."""
    profile_data = {
        "community": {},
        "global": {},
        "offchain": {},
        "user": {},
        "transaction": {},
        "discussion": {},
        "routing": {},
        "app": {},
        "userProfiles": {
            "profiles": {
                "blocktrades": {
                    "active": "2026-04-03T15:42:30",
                    "created": "2016-03-30T00:04:33",
                    "name": "blocktrades",
                    "context": {"followed": False, "muted": False},
                    "metadata": {
                        "profile": {
                            "about": "Exchange cryptocurrency fast and easy",
                            "cover_image": "https://example.com/cover.jpg",
                            "location": "Worldwide",
                            "name": "BlockTrades",
                            "profile_image": "https://example.com/avatar.png",
                            "website": "https://blocktrades.us",
                        }
                    },
                    "post_count": 4904,
                    "reputation": 79.75,
                    "id": 441,
                    "stats": {"followers": 30932, "following": 47, "rank": 0},
                }
            }
        },
        "search": {},
    }
    html = f'<script type="application/json" data-iso-key="_0">{json.dumps(profile_data)}</script>'
    info = extract(html)
    assert info.get('uid') == '441'
    assert info.get('username') == 'blocktrades'
    assert info.get('fullname') == 'BlockTrades'
    assert info.get('bio') == 'Exchange cryptocurrency fast and easy'
    assert info.get('image') == 'https://example.com/avatar.png'
    assert info.get('image_bg') == 'https://example.com/cover.jpg'
    assert info.get('website') == 'https://blocktrades.us'
    assert info.get('location') == 'Worldwide'
    assert info.get('reputation') == '79.75'
    assert info.get('posts_count') == '4904'
    assert info.get('follower_count') == '30932'
    assert info.get('following_count') == '47'
    assert info.get('created_at') == '2016-03-30T00:04:33'
    assert info.get('latest_activity_at') == '2026-04-03T15:42:30'


def test_hive_blog_empty_profile():
    """Hive Blog: user with empty metadata fields returns None for optional fields."""
    profile_data = {
        "community": {},
        "global": {},
        "userProfiles": {
            "profiles": {
                "newuser": {
                    "active": "2025-01-01T00:00:00",
                    "created": "2025-01-01T00:00:00",
                    "name": "newuser",
                    "metadata": {
                        "profile": {
                            "about": "",
                            "cover_image": "",
                            "location": "",
                            "name": "",
                            "profile_image": "",
                            "website": "",
                        }
                    },
                    "post_count": 0,
                    "reputation": 25,
                    "id": 999999,
                    "stats": {"followers": 0, "following": 0},
                }
            }
        },
    }
    html = f'<script type="application/json" data-iso-key="_0">{json.dumps(profile_data)}</script>'
    info = extract(html)
    assert info.get('uid') == '999999'
    assert info.get('username') == 'newuser'
    assert info.get('fullname') is None
    assert info.get('bio') is None
    assert info.get('image') is None
    assert info.get('website') is None


def test_vimeo_html_ld_json():
    """Vimeo HTML: extract profile from ld+json ProfilePage with social crosslinks."""
    ld_json = json.dumps([{
        "dateCreated": "2006-12-11T19:57:24Z",
        "dateModified": "2022-08-01T02:48:55Z",
        "url": "https://vimeo.com/testuser",
        "mainEntity": {
            "@type": "Person",
            "name": "Test User",
            "identifier": 12345,
            "alternateName": "testuser",
            "interactionStatistic": {
                "@type": "InteractionCounter",
                "interactionType": "https://schema.org/FollowAction",
                "userInteractionCount": 1621,
            },
            "agentInteractionStatistic": {
                "@type": "InteractionCounter",
                "interactionType": "https://schema.org/WriteAction",
                "userInteractionCount": 519,
            },
            "description": "Bio with &#039;quotes&#039; and entities",
            "image": "https://i.vimeocdn.com/portrait/12345_640x640",
            "url": "/testuser",
            "sameAs": [
                "https://vimeo.com/testuser",
                "http://testuser.example.com",
                "http://twitter.com/testuser",
                "https://www.instagram.com/testuser/",
                "https://www.facebook.com/testuser/",
                "https://www.youtube.com/@testuser/",
                "https://www.tiktok.com/@testuser",
                "https://www.linkedin.com/in/testuser/",
            ],
        },
        "potentialAction": {
            "@type": "ViewAction",
            "target": "vimeo://app.vimeo.com/users/12345",
        },
        "@type": "ProfilePage",
        "@context": "http://schema.org",
    }])
    html_page = (
        '<!DOCTYPE html><html><head>'
        f'<script type="application/ld+json">{ld_json}</script>'
        '</head><body></body></html>'
    )
    info = extract(html_page)
    assert info.get('uid') == '12345'
    assert info.get('username') == 'testuser'
    assert info.get('fullname') == 'Test User'
    assert info.get('bio') == "Bio with 'quotes' and entities"
    assert 'vimeocdn.com' in info.get('image', '')
    assert info.get('created_at') == '2006-12-11T19:57:24Z'
    assert info.get('updated_at') == '2022-08-01T02:48:55Z'
    assert info.get('follower_count') == '1621'
    assert info.get('videos_count') == '519'
    assert info.get('twitter_url') == 'http://twitter.com/testuser'
    assert info.get('instagram_url') == 'https://www.instagram.com/testuser/'
    assert info.get('facebook_url') == 'https://www.facebook.com/testuser/'
    assert info.get('youtube_url') == 'https://www.youtube.com/@testuser/'
    assert info.get('tiktok_url') == 'https://www.tiktok.com/@testuser'
    assert info.get('linkedin_url') == 'https://www.linkedin.com/in/testuser/'
    # vimeo.com self-link should be excluded from `links`
    assert 'vimeo.com/testuser' not in info.get('links', '')
    assert 'testuser.example.com' in info.get('links', '')


def test_vimeo_html_minimal_profile():
    """Vimeo HTML: profile with no external links and no description."""
    ld_json = json.dumps([{
        "dateCreated": "2020-01-01T00:00:00Z",
        "dateModified": "2020-01-01T00:00:00Z",
        "url": "https://vimeo.com/minimal",
        "mainEntity": {
            "@type": "Person",
            "name": "Minimal",
            "identifier": 99999,
            "alternateName": "minimal",
            "image": "https://i.vimeocdn.com/portrait/default",
            "sameAs": ["https://vimeo.com/minimal"],
        },
        "potentialAction": {"target": "vimeo://app.vimeo.com/users/99999"},
        "@type": "ProfilePage",
    }])
    html_page = (
        '<!DOCTYPE html><html><head>'
        f'<script type="application/ld+json">{ld_json}</script>'
        '</head><body></body></html>'
    )
    info = extract(html_page)
    assert info.get('uid') == '99999'
    assert info.get('username') == 'minimal'
    assert info.get('fullname') == 'Minimal'
    assert info.get('bio') is None
    assert info.get('twitter_url') is None
    assert info.get('links') is None


def test_discourse_api_json():
    """Discourse API: extract user fields from JSON response."""
    body = json.dumps({
        "user": {
            "id": 42,
            "username": "jdoe",
            "name": "John Doe",
            "title": "Regular",
            "bio_raw": "Hello from Discourse.",
            "website": "https://example.com",
            "location": "New York",
            "avatar_template": "/user_avatar/meta.discourse.org/jdoe/{size}/1234.png",
            "trust_level": 2,
            "moderator": False,
            "admin": False,
            "badge_count": 5,
            "profile_view_count": 100,
            "created_at": "2020-01-15T10:00:00.000Z",
            "last_seen_at": "2024-03-01T08:30:00.000Z",
        },
        "trust_level": 2,
        "badge_count": 5,
        "profile_view_count": 100,
    })
    info = extract(body)
    assert info.get('uid') == '42'
    assert info.get('username') == 'jdoe'
    assert info.get('fullname') == 'John Doe'
    assert info.get('title') == 'Regular'
    assert info.get('bio') == 'Hello from Discourse.'
    assert info.get('website') == 'https://example.com'
    assert info.get('location') == 'New York'
    assert '240' in info.get('image', '')
    assert info.get('trust_level') == '2'
    assert info.get('badge_count') == '5'
    assert info.get('views_count') == '100'
    assert info.get('created_at') == '2020-01-15T10:00:00.000Z'
    assert info.get('latest_activity_at') == '2024-03-01T08:30:00.000Z'


def test_github_api_url_mutations():
    """GitHub API: profile URLs of shape `github.com/{username}` are
    rewritten to the REST endpoint `api.github.com/users/{username}`
    so the CLI can fetch the JSON user object automatically. The
    mutation must match the bare profile path only — repo paths
    (e.g. `github.com/torvalds/linux`) must not fire so we don't
    waste an API hit on `/users/torvalds/linux`."""
    from socid_extractor.main import mutate_url

    # Bare profile URL → API user endpoint
    for url in (
        'https://github.com/soxoj',
        'http://github.com/soxoj',
        'https://www.github.com/soxoj',
        'https://github.com/soxoj/',
    ):
        urls = [r[0] for r in mutate_url(url)]
        assert 'https://api.github.com/users/soxoj' in urls, url

    # Repo URL must NOT be rewritten to /users/torvalds/linux
    urls = [r[0] for r in mutate_url('https://github.com/torvalds/linux')]
    assert not any('api.github.com/users/' in u for u in urls)


def test_github_social_accounts_api():
    """GitHub /users/{u}/social_accounts: separate endpoint that lists
    accounts the main /users/{u} response doesn't expose. Schema must
    fire on this array shape, surface every URL in `links`, and parse
    handles for each known provider (twitter, bluesky, mastodon,
    linkedin, youtube, twitch, facebook, instagram, reddit)."""
    # Real GitHub API responses are compact (no whitespace) — flag
    # `'"provider":"'` won't match if json.dumps adds default spaces.
    page = json.dumps([
        {"provider": "twitter",   "url": "https://twitter.com/sox0j"},
        {"provider": "bluesky",   "url": "https://bsky.app/profile/soxoj.bsky.social"},
        {"provider": "mastodon",  "url": "https://infosec.exchange/@soxoj"},
        {"provider": "linkedin",  "url": "https://www.linkedin.com/in/soxoj/"},
        {"provider": "youtube",   "url": "https://www.youtube.com/@soxoj"},
        {"provider": "twitch",    "url": "https://www.twitch.tv/soxoj"},
        {"provider": "facebook",  "url": "https://www.facebook.com/soxoj"},
        {"provider": "instagram", "url": "https://www.instagram.com/soxoj"},
        {"provider": "reddit",    "url": "https://www.reddit.com/user/soxoj"},
    ], separators=(',', ':'))
    info = extract(page)
    assert info.get('_extractor') == 'GitHub Social Accounts API'
    assert info.get('twitter_username') == 'sox0j'
    assert info.get('bluesky_username') == 'soxoj'
    assert info.get('mastodon_username') == 'soxoj'
    assert info.get('linkedin_username') == 'soxoj'
    assert info.get('youtube_username') == 'soxoj'
    assert info.get('twitch_username') == 'soxoj'
    assert info.get('facebook_username') == 'soxoj'
    assert info.get('instagram_username') == 'soxoj'
    assert info.get('reddit_username') == 'soxoj'
    assert 'https://bsky.app/profile/soxoj.bsky.social' in info.get('links', '')
    assert 'https://infosec.exchange/@soxoj' in info.get('links', '')


def test_github_social_accounts_api_keeps_bluesky_custom_domain():
    """GitHub social accounts: custom Bluesky domains are preserved."""
    page = json.dumps([
        {"provider": "bluesky", "url": "https://bsky.app/profile/jay.bsky.team"},
    ], separators=(',', ':'))
    info = extract(page)
    assert info.get('bluesky_username') == 'jay.bsky.team'


def test_github_social_accounts_url_mutation():
    """GitHub Social Accounts API: bare profile URL `github.com/{u}`
    auto-mutates to the social_accounts endpoint so the CLI can fetch
    Bluesky/Mastodon/etc. without a second manual call."""
    from socid_extractor.main import mutate_url
    urls = [r[0] for r in mutate_url('https://github.com/soxoj')]
    assert 'https://api.github.com/users/soxoj/social_accounts' in urls


def test_gitlab_api_with_public_email():
    """Gitlab API: response from /api/v4/users?username=… exposes
    `public_email` and `web_url` in addition to the basic identity
    fields. The scheme requires `"public_email"` in flags so it only
    fires on the array-form user-search response, then surfaces the
    email as both `email` and `emails`, and the profile URL as
    `website`."""
    page = json.dumps([{
        "id": 1244269,
        "username": "ainslie",
        "public_email": "ainslie@example.com",
        "name": "ainslie cleverdon",
        "state": "active",
        "avatar_url": "https://secure.gravatar.com/avatar/eb7d.jpg",
        "web_url": "https://gitlab.com/ainslie",
    }])
    info = extract(page)
    assert info.get('_extractor') == 'Gitlab API'
    assert info.get('uid') == '1244269'
    assert info.get('username') == 'ainslie'
    assert info.get('fullname') == 'ainslie cleverdon'
    assert info.get('state') == 'active'
    assert info.get('email') == 'ainslie@example.com'
    assert 'ainslie@example.com' in info.get('emails', '')
    assert info.get('website') == 'https://gitlab.com/ainslie'


def _deviantart_fixture(extra_user_fields=''):
    """Build a minimal page that triggers the DeviantArt scheme.

    The embedded user object is in the same escaped-JSON shape DeviantArt
    uses (`\\"key\\":\\"val\\"`). `extra_user_fields` lets a test append
    fields *after* `legacyTextEditUrl` — the position where the old
    regex terminator would stop, leaving unbalanced braces.
    """
    user = (
        r'{\"username\":\"rootkea\",\"country\":\"Antarctica\",'
        r'\"gender\":\"\",\"tagline\":\"hi\",\"website\":\"x.com\",'
        r'\"socialLinks\":[],\"twitterUsername\":\"\",'
        r'\"textContent\":{\"excerpt\":\"bio\"},'
        r'\"devidDeviation\":{\"author\":{\"usericon\":\"u.jpg\"}},'
        r'\"deviantFor\":352125671,'
        r'\"legacyTextEditUrl\":\"\\\/users\\\/edit\"'
        + (',' + extra_user_fields if extra_user_fields else '')
        + r'}'
    )
    return '<script>window.deviantART = {};\n' + user + '\n</script>'


def test_deviantart_user_object_with_trailing_fields_does_not_crash():
    """Regression for soxoj/socid-extractor#255.

    Some DeviantArt profiles embed user fields *after* `legacyTextEditUrl`
    (e.g. `isNewDeviant`). The old regex terminator `legacyTextEditUrl.+?})`
    stopped at the first `})` inside `devidDeviation`, leaving the captured
    slice with unbalanced braces and crashing `json.loads` in `extract()`.
    The fix widens the regex and uses `raw_decode` to trim at the real
    matching brace.
    """
    page = _deviantart_fixture(
        extra_user_fields=r'\"isNewDeviant\":false,\"isWatching\":false'
    )
    info = extract(page)
    assert info.get('_extractor') == 'DeviantArt'
    assert info.get('username') == 'rootkea'
    assert info.get('country') == 'Antarctica'


def test_deviantart_user_object_without_trailing_fields_still_works():
    """The fix must not regress the simpler shape (no fields after
    `legacyTextEditUrl`) that the original regex was written for.
    """
    info = extract(_deviantart_fixture())
    assert info.get('_extractor') == 'DeviantArt'
    assert info.get('username') == 'rootkea'
    assert info.get('country') == 'Antarctica'
