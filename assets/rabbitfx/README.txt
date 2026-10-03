Setting cache_shaders to 1 should improve performance between game sessions
by saving processed shaders after loading something for the first time.

Enabling this will cause the game to lag initially as it generates files
but it will reduce loading times in the future.

Please note that the shader cache will effectively be reset whenever 
there is a big game update, or there when there is an update to RabbitFX
that involves major fixes, feature additions, and pattern optimizations.

Unfortunately when the shader cache is reset, stutters will return 
temporarily as the cache is rebuilt.
 
If you already have shader cache enabled, the following step
does not need to be repeated.

To enable shader cache, make a copy of ShaderCacheSettings.ini
and put it inside the RabbitFX folder.