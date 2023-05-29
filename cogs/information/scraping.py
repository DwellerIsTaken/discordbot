from __future__ import annotations

import wikipediaapi
import datetime
import discord
import re

from yarl import URL
from aiospotify import http
from aiospotify import (
    Album,
    Artist,
    Image,
    ObjectType,
    PartialAlbum,
    PartialArtist,
    PartialTrack,
    SearchResult,
    SpotifyClient,
    Track,
)

from discord import app_commands
from discord.ext import commands, tasks

from typing import Any, List, Dict, Tuple, Optional, Literal, Union
from typing_extensions import Self

import constants as cs
from utils import BaseCog, capitalize_greek_numbers
from bot import Dwello, DwelloContext, get_or_fail

TMDB_KEY = get_or_fail('TMDB_API_TOKEN')
SPOTIFY_CLIENT_ID = get_or_fail('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = get_or_fail('SPOTIFY_CLIENT_SECRET')

class Scraping(BaseCog):

    def __init__(self: Self, bot: Dwello, *args: Any, **kwargs: Any):
        super().__init__(bot, *args, **kwargs)
        
        #self.session = self.bot.session
        
        self.spotify_client: SpotifyClient = SpotifyClient(
            SPOTIFY_CLIENT_ID,
            SPOTIFY_CLIENT_SECRET,
            session=self.bot.session,
        )
        
        """base: route.Base = route.Base(
            session=self.bot.session,
            language="en",
            region="US",    
        )
        base.key = TMDB_KEY"""
        
    @property
    def tmdb_key(self: Self) -> str:
        _key: str = get_or_fail('TMDB_API_TOKEN')
        return _key
        
    @property
    def tmdb_headers(self: Self) -> Dict[str, str]:
        _headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self.tmdb_key}"
        }
        return _headers
    
    @property
    def spotify_http_client(self: Self) -> http.HTTPClient:
        return self.spotify_client.http
    
    '''@property
    def spotify_headers(self: Self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.spotify_token}"}'''
    
    """async def get_spotify_access_token(self: Self) -> Tuple[str, int]:
        
        client_id: str = get_or_fail('SPOTIFY_CLIENT_ID')
        client_secret: str = get_or_fail('SPOTIFY_CLIENT_SECRET')
        
        #client: aiospotify.SpotifyClient = aiospotify.SpotifyClient(client_id, client_secret)

        auth_bytes: bytes = f"{client_id}:{client_secret}".encode("utf-8")
        auth_base = str(base64.b64encode(auth_bytes), "utf-8")
        
        auth_url: URL = "https://accounts.spotify.com/api/token"
        auth_headers: Dict[str, str] = {
            "Authorization": "Basic " + auth_base,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        auth_data: Dict[str, str] = {"grant_type": "client_credentials"}
        async with self.bot.session.post(url=auth_url, headers=auth_headers, data=auth_data) as response:  
            data: Any = await response.json()
            
        match response.status:
            case 200:
                _token = data['access_token']
                _expires = data['expires_in']
            case 400:
                return "The request was invalid or malformed. This could be due to missing or incorrect parameters."
            case 401:
                return "The request lacks valid authentication credentials." # temp
            case 403:
                return "The server understood the request, but you are not allowed to access the requested resource."
        
        self.spotify_token = _token
        return _token, _expires"""
    
    def get_unix_timestamp(self: Self, _date_string: str, _format: str, /, style: discord.utils.TimestampStyle) -> str:
        
        _date = datetime.datetime.strptime(_date_string, _format)
        _seconds = (_date - datetime.datetime(1970, 1, 1)).total_seconds()
    
        if style is None:
            return f'<t:{int(_seconds)}>'
        return f'<t:{int(_seconds)}:{style}>'
    
    @commands.hybrid_command(name="album", help="Returns an album.", aliases=["albums"], with_app_command=True)
    async def album(self: Self, ctx: DwelloContext, *, album: str) -> Optional[discord.Message]:
        
        data: SearchResult = await self.spotify_client.search(query=album, types=[ObjectType.Album], limit=5)
            
        albums: List[Dict[str, Any]] = data._data['albums']['items']
        if not albums:
            return await ctx.reply(f"Can't find any albums by the name of *{discord.utils.escape_markdown(album, as_needed=False)}*", user_mistake=True)
        
        album: Dict[str, Any] = albums[0]
        
        _id = album['id']
        name = album['name']
        release_date = album['release_date']
        link = album['external_urls']['spotify']
        image_url = album['images'][1]['url'] if album['images'] else None
        
        artists = [(artist['name'], artist['external_urls']['spotify']) for artist in album['artists']][:2]
        
        embed: discord.Embed = discord.Embed(
            title=name,
            url=link,
            color=cs.RANDOM_COLOR,
        )
        embed.set_thumbnail(url=image_url)
        embed.add_field(name="Release Date", value=self.get_unix_timestamp(release_date, "%Y-%m-%d", style="d"), inline=False)
        
        tracks_data: Dict[str, Any] = await self.spotify_http_client.get_album_tracks(id=_id, market="US", limit=5)
        
        tracks: List[Dict[str, Any]] = tracks_data['items']
        if tracks:
            embed.add_field(name="Tracks", value="\n".join([f"> [{track['name']}]({track['external_urls']['spotify']})" for track in tracks]))
            
        embed.add_field(
            name="Artist" if len(artists) == 1 else "Artists",
            value="\n".join([f"> [{i[0].title()}]({i[1]})" for i in artists]),
        )
            
        return await ctx.reply(embed=embed)
    
    @commands.hybrid_command(name="artist", help="Returns an artist.", aliases=["artists"], with_app_command=True)
    async def artist(self: Self, ctx: DwelloContext, *, artist: str) -> Optional[discord.Message]:
        
        data: SearchResult = await self.spotify_client.search(query=artist, types=[ObjectType.Artist], limit=5)
            
        artists: List[Artist] = data.artists.items
        if not artists:
            return await ctx.reply(f"Can't find any artists by the name of *{discord.utils.escape_markdown(artist, as_needed=False)}*", user_mistake=True)

        artist: Artist = artists[0]
        
        album_data: Dict[str, Any] = await self.spotify_http_client.get_artist_albums(id=artist.id, include_groups=["album"], market="US", limit=5)
        
        tracks_data: Dict[str, Any] = await self.spotify_http_client.get_artist_top_tracks(id=artist.id, market="US")
        
        albums = album_data['items']
        
        unique_albums = sorted(albums, key=lambda x: x['name'].split(' (')[0])
        unique_albums = [album for i, album in enumerate(unique_albums) if not any(album['name'].split(' (')[0].lower() in a['name'].lower() for a in unique_albums[:i])]
        
        album_names = [re.sub(r'\([^()]+\)', '', album['name']).strip().lower() for album in unique_albums[:3]]
        album_names.sort(key=lambda x: len(x))
        
        sorted_unique_albums = sorted(unique_albums[:3], key=lambda x: album_names.index(re.sub(r'\([^()]+\)', '', x['name']).strip().lower()))
        album_tuples = [(capitalize_greek_numbers(name.title()), album['external_urls']['spotify']) for name, album in zip(album_names, sorted_unique_albums)]
            
        tracks: List[Dict[str, Any]] = tracks_data['tracks']
        top_tracks = sorted(tracks, key=lambda x: x['popularity'], reverse=True)

        _description = f"**Followers**: {artist.followers.total:,}\n**Genres**: " + ", ".join([genre for genre in artist.genres[:2]])
        embed: discord.Embed = discord.Embed(
            title=artist.name,
            url=artist.external_urls.spotify,
            description=_description,
            color=cs.RANDOM_COLOR,
        )
        image: Image = artist.images[1] if artist.images else None
        if image:
            embed.set_thumbnail(url=image.url)
        embed.add_field(name="Top Albums", value="\n".join(f"> [{name}]({url})" for name, url in album_tuples)) # •
        embed.add_field(name="Top Tracks", value="\n".join(f"> [{track['name']}]({track['external_urls']['spotify']})" for track in top_tracks[:3]))
        
        return await ctx.reply(embed=embed)
    
    @commands.hybrid_command(name="playlist", help="Returns a playlist.", aliases=["playlists"], with_app_command=True)
    async def playlist(self: Self, ctx: DwelloContext, *, playlist: str) -> Optional[discord.Message]:
        
        data: SearchResult = await self.spotify_client.search(query=playlist, types=[ObjectType.Playlist], limit=5)
            
        playlists: List[Dict[str, Any]] = data._data['playlists']['items']
        if not playlists:
            return await ctx.reply(f"Can't find any playlists by the name of *{discord.utils.escape_markdown(playlist, as_needed=False)}*", user_mistake=True)
        
        playlist: Dict[str, Any] = playlists[0]
        
        name = playlist['name']
        url = playlist['external_urls']['spotify']
        total_tracks = playlist['tracks']['total']
        owner_name = playlist['owner']['display_name']
        owner_url = playlist['owner']['external_urls']['spotify']
        image_url = playlist['images'][0]['url'] if playlist['images'] else None
        description = playlist['description'] if playlist['description'] else None

        embed: discord.Embed = discord.Embed(
            title=name,
            url=url,
            description=description,
            color=cs.RANDOM_COLOR,
        )
        if image_url:
            embed.set_thumbnail(url=image_url)
        embed.add_field(name="Owner", value=f"[{owner_name}]({owner_url})")
        embed.add_field(name="Total Tracks", value=total_tracks)
        
        return await ctx.reply(embed=embed)
    
    @commands.hybrid_command(name="track", help="Returns a track.", aliases=["tracks"], with_app_command=True)
    async def track(self: Self, ctx: DwelloContext, *, track: str) -> Optional[discord.Message]:
        
        data: SearchResult = await self.spotify_client.search(query=track, types=[ObjectType.Track], limit=5)
            
        tracks: List[Track] = data.tracks.items
        if not tracks:
            return await ctx.reply(f"Can't find any tracks by the name of *{discord.utils.escape_markdown(track, as_needed=False)}*", user_mistake=True)
        
        _track: Track = tracks[0]
        _album: PartialAlbum = _track.album
        _artists: List[Tuple[str, str]] = [(artist.name, artist.external_urls.spotify) for artist in _track.artists][:2]
        
        duration_in_minutes = _track.duration / 1000 / 60
        
        duration_str = f"**Duration**: {'{:.2f}'.format(duration_in_minutes)} min" if duration_in_minutes >= 1 else '{:.2f}'.format(_track.duration / 1000) + " sec"
        release_str = f"\n**Release Date**: " + self.get_unix_timestamp(_album.release_date.date, '%Y-%m-%d', style='d')
        embed: discord.Embed = discord.Embed(
            title=_track.name,
            url=f"https://open.spotify.com/track/{_track.id}",
            description=duration_str+release_str,
            color=cs.RANDOM_COLOR,
        )
        image: Image = _album.images[1] if _album.images else None
        if image:
            embed.set_thumbnail(url=image.url)
        embed.add_field(
            name="Artist" if len(_artists) == 1 else "Artists",
            value="\n".join([f"> [{i[0].title()}]({i[1]})" for i in _artists]),
        )
        embed.add_field(name="Album", value=f"[{_album.name}]({_album.external_urls.spotify})")
        
        return await ctx.reply(embed=embed)
        
    @commands.hybrid_command(name="actor", help="Returns a person who's known in the movie industry.", aliases=["actors", "actress", "actresses"], with_app_command=True) # amybe people alias, but later if there are no other ppl aliases
    async def movie_person(self: Self, ctx: DwelloContext, *, person: str) -> Optional[discord.Message]:
        
        pages: int = 1
        url: URL = "https://api.themoviedb.org/3/search/person?query=%s&include_adult=%s&language=en-US&page=%s" % (person, True, pages)
        async with self.bot.session.get(url=url, headers=self.tmdb_headers) as response:  
            data = await response.json()

        if response.status != 200:
            return await ctx.reply("Couldn't connect to the API.", user_mistake=True)
        
        try:
            person = max(data['results'], key=lambda _person: _person['popularity'])
            
        except ValueError:
            return await ctx.reply(f"Couldn't find a person by the name of {person}.", user_mistake=True)
        
        wiki = wikipediaapi.Wikipedia('en')
        page: wikipediaapi.WikipediaPage = wiki.page(person['name'])
        
        embed: discord.Embed = discord.Embed(
            title=person['original_name'],
            description=page.summary,
            url=f"https://www.themoviedb.org/person/{person['id']}",
            color=cs.RANDOM_COLOR,
        )
        #rd: List[str] = movie['release_date'].split('-')
        #year, month, day = int(rd[0]), int(rd[1]), int(rd[2])
        #release_date: datetime.datetime = datetime.datetime(year, month, day, tzinfo=None)
        
        #embed.add_field(name='Release Date', value=discord.utils.format_dt(release_date, style='d'))
        
        gender = 'Male' if person['gender'] == 2 else 'Female'
        top_movies = [movie for movie in person['known_for']]

        embed.add_field(name='Gender', value=gender)
        #embed.add_field(name='Age', value=None)
        embed.add_field(name='Department', value=person['known_for_department'])
        
        top_movies_desc: str = ""
        for movie in top_movies:
            top_movies_desc += f"\n• [{movie['title']}](https://www.themoviedb.org/movie/{movie['id']})"
            
        if top_movies_desc:
            embed.add_field(name="Top Movies", value=top_movies_desc, inline=False)

        if person['profile_path']:
            embed.set_thumbnail(url=f"https://image.tmdb.org/t/p/w500{person['profile_path']}")

        embed.set_footer(text=f"Popularity: {person['popularity']}")

        return await ctx.reply(embed=embed)
        
    @commands.command(name="movie", help="Returns a movie by its title.", aliases=["film", "films", "movies"])
    async def movie(self: Self, ctx: DwelloContext, *, movie: str) -> Optional[discord.Message]:
        #Docs: https://developer.themoviedb.org/reference/intro/getting-started
        
        pages: int = 1
        url: URL = "https://api.themoviedb.org/3/search/movie?query=%s&include_adult=%s&language=en-US&page=%s" % (movie, True, pages)
        async with self.bot.session.get(url=url, headers=self.tmdb_headers) as response:  
            data = await response.json()

        if response.status != 200:
            return await ctx.reply("Couldn't connect to the API.", user_mistake=True)
        
        try:
            movie = max(data['results'], key=lambda _movie: _movie['vote_count'])
            
        except ValueError:
            return await ctx.reply(f"Couldn't find a movie by the name of {movie}.", user_mistake=True)

        embed: discord.Embed = discord.Embed(
            title=movie['title'],
            description=movie['overview'],
            url=f"https://www.themoviedb.org/movie/{movie['id']}",
            color=cs.RANDOM_COLOR,
        )
        embed.add_field(name='Release Date', value=self.get_unix_timestamp(movie['release_date'], "%Y-%m-%d", style="d"))
        embed.add_field(name='Vote Average', value=f"{str(movie['vote_average'])[:3]} / 10")
        embed.add_field(name='Vote Count', value=movie['vote_count'])

        if movie['poster_path']:
            embed.set_thumbnail(url=f"https://image.tmdb.org/t/p/w500{movie['poster_path']}")

        embed.set_footer(text=f"Popularity: {movie['popularity']}")

        return await ctx.reply(embed=embed)     
    
    @app_commands.command(name="movie", description="Returns a movie by its title.")
    async def _movie(self: Self, ctx: DwelloContext, *, movie: str, year: int = None) -> Optional[discord.Message]:
        
        pages: int = 1   
        
        url: URL = "https://api.themoviedb.org/3/search/movie?query=%s&include_adult=%s&language=en-US&primary_release_year=%s&page=%s" % (movie, True, year, pages)
        
        if not year:
            url = "https://api.themoviedb.org/3/search/movie?query=%s&include_adult=%s&language=en-US&page=%s" % (movie, True, pages)
        
        async with self.bot.session.get(url=url, headers=self.tmdb_headers) as response:  
            data = await response.json()
        
        if response.status != 200:
            return await ctx.reply("Couldn't connect to the API.", user_mistake=True)
           
        try: 
            movie = max(data['results'], key=lambda _movie: _movie['vote_count'])
            
        except ValueError:
            return await ctx.reply(f"Couldn't find a movie by the name of {movie}.", user_mistake=True)

        embed: discord.Embed = discord.Embed(
            title=movie['title'],
            description=movie['overview'],
            url=f"https://www.themoviedb.org/movie/{movie['id']}",
            color=cs.RANDOM_COLOR,
        )   
        embed.add_field(name='Release Date', value=self.get_unix_timestamp(movie['release_date'], "%Y-%m-%d", style="d"))
        embed.add_field(name='Vote Average', value=f"{str(movie['vote_average'])[:3]} / 10")
        embed.add_field(name='Vote Count', value=movie['vote_count'])

        if movie['poster_path']:
            embed.set_thumbnail(url=f"https://image.tmdb.org/t/p/w500{movie['poster_path']}")

        embed.set_footer(text=f"Popularity: {movie['popularity']}")

        return await ctx.reply(embed=embed)
    
    @commands.command(name="show", help="Returns a TV show by its title.", aliases=["series", "shows"])
    async def show(self: Self, ctx: DwelloContext, *, show: str) -> Optional[discord.Message]:
        
        pages: int = 1
        url: URL = "https://api.themoviedb.org/3/search/tv?query=%s&include_adult=%s&language=en-US&page=%s" % (show, True, pages)      
        async with self.bot.session.get(url=url, headers=self.tmdb_headers) as response:  
            data = await response.json()
        
        if response.status != 200:
            return await ctx.reply("Couldn't connect to the API.", user_mistake=True)
          
        try:  
            show = max(data['results'], key=lambda _show: _show['vote_count'])
            
        except ValueError:
            return await ctx.reply(f"Couldn't find a show by the name of {show}.", user_mistake=True)

        embed: discord.Embed = discord.Embed(
            title=show['original_name'],
            description=show['overview'],
            url=f"https://www.themoviedb.org/tv/{show['id']}",
            color=cs.RANDOM_COLOR,
        )   
        embed.add_field(name='Release Date', value=self.get_unix_timestamp(show['first_air_date'], "%Y-%m-%d", style="d"))
        embed.add_field(name='Vote Average', value=f"{str(show['vote_average'])[:3]} / 10")
        embed.add_field(name='Vote Count', value=show['vote_count'])

        if show['poster_path']:
            embed.set_thumbnail(url=f"https://image.tmdb.org/t/p/w500{show['poster_path']}")

        embed.set_footer(text=f"Popularity: {show['popularity']}")

        return await ctx.reply(embed=embed)    
    
    @app_commands.command(name="show", description="Returns a TV show by its title.")
    async def _show(self: Self, ctx: DwelloContext, *, show: str, year: int = None) -> Optional[discord.Message]:
        
        pages: int = 1
        
        url: URL = "https://api.themoviedb.org/3/search/movie?query=%s&include_adult=%s&language=en-US&primary_release_year=%s&page=%s" % (show, True, year, pages)
        
        if not year:
            url = "https://api.themoviedb.org/3/search/movie?query=%s&include_adult=%s&language=en-US&page=%s" % (show, True, pages)
        
        async with self.bot.session.get(url=url, headers=self.tmdb_headers) as response:  
            data = await response.json()
        
        if response.status != 200:
            return await ctx.reply("Couldn't connect to the API.", user_mistake=True)
            
        try:
            show = max(data['results'], key=lambda _show: _show['vote_count'])
            
        except ValueError:
            return await ctx.reply(f"Couldn't find a show by the name of {show}.", user_mistake=True)

        embed: discord.Embed = discord.Embed(
            title=show['original_name'],
            description=show['overview'],
            url=f"https://www.themoviedb.org/tv/{show['id']}",
            color=cs.RANDOM_COLOR,
        )
        embed.add_field(name='Release Date', value=self.get_unix_timestamp(show['first_air_date'], "%Y-%m-%d", style="d"))
        embed.add_field(name='Vote Average', value=f"{str(show['vote_average'])[:3]} / 10")
        embed.add_field(name='Vote Count', value=show['vote_count'])

        if show['poster_path']:
            embed.set_thumbnail(url=f"https://image.tmdb.org/t/p/w500{show['poster_path']}")

        embed.set_footer(text=f"Popularity: {show['popularity']}")

        return await ctx.reply(embed=embed)