import os
import io
import json
import zipfile
import re
import struct
import lupa


class Mod:
    def _load_info(self):
        with self.get_file('info.json') as f:
            self.info = json.load(f)

    def get_file(self, file):
        return NotImplementedError

    def get_binary(self, file):
        return NotImplementedError

    def exists(self, file):
        return NotImplementedError

    def listdir(self, path):
        return NotImplementedError

    @staticmethod
    def get_mod(path):
        if os.path.isdir(path):
            if os.path.exists(os.path.join(path, 'info.json')):
                return DirMod(path)
        if os.path.isfile(path) and path.endswith('.zip'):
            with zipfile.ZipFile(path) as f:
                if os.path.basename(path)[:-4]+'/info.json' in f.namelist():
                    return ZipMod(path)
        return None

    @staticmethod
    def version_compare(a, b):
        a = list(map(int, a.split('.')))
        b = list(map(int, b.split('.')))
        while len(a) < 3:
            a.append(0)
        while len(b) < 3:
            b.append(0)
        for i in range(3):
            if a[i] != b[i]:
                return a[i] - b[i]
        return 0


class DirMod(Mod):
    def __init__(self, path):
        self.path = path
        self._load_info()

    def get_file(self, file):
        return open(os.path.join(self.path, *file.split('/')), encoding='utf-8-sig')

    def get_binary(self, file):
        return open(os.path.join(self.path, *file.split('/')), 'rb')

    def exists(self, file):
        return os.path.exists(os.path.join(self.path, *file.split('/')))

    def listdir(self, path):
        files = os.listdir(os.path.join(self.path, *path.split('/')))
        return [path+'/'+f for f in files]


class ZipMod(Mod):
    def __init__(self, path):
        assert path.endswith('.zip')
        self.path = os.path.basename(path)[:-4] + '/'
        self.zipfile = zipfile.ZipFile(path)
        self._load_info()

    def get_file(self, file):
        file = re.sub('/+', '/', file)
        return io.TextIOWrapper(self.zipfile.open(self.path+file), encoding='utf-8-sig')

    def get_binary(self, file):
        file = re.sub('/+', '/', file)
        # return self.zipfile.open(self.path+file, 'r')
        with self.zipfile.open(self.path + file, 'r') as f:
            data = f.read()
        return io.BytesIO(data)

    def exists(self, file):
        file = re.sub('/+', '/', file)
        return self.path+file in self.zipfile.namelist()

    def listdir(self, path):
        return [f[len(self.path):] for f in self.zipfile.namelist() if f.startswith(self.path+path)]

    def __del__(self):
        self.zipfile.close()


class ModManager:
    def __init__(self, game_dir, mods_dir):
        self.game_dir = game_dir
        self.mods_dir = mods_dir
        self.mods = self.get_all_mods()
        self.mod_order = ModManager.resolve_dependency(self.mods)

    def get_all_mods(self):
        mods = {}
        for file in os.listdir(os.path.join(self.game_dir, 'data')):
            mod = Mod.get_mod(os.path.join(self.game_dir, 'data', file))
            if mod is not None:
                name = mod.info['name']
                version = '0.0.0' if name == 'core' else mod.info['version']
                if name not in mods:
                    mods[name] = {}
                mods[name][version] = mod
        for file in os.listdir(self.mods_dir):
            mod = Mod.get_mod(os.path.join(self.mods_dir, file))
            if mod is not None:
                name = mod.info['name']
                version = mod.info['version']
                if name not in mods:
                    mods[name] = {}
                mods[name][version] = mod

        with open(os.path.join(self.mods_dir, 'mod-list.json')) as f:
            mod_list = json.load(f)
        enabled_mods = {'core': mods['core']['0.0.0']}
        for mod in mod_list['mods']:
            if mod['enabled']:
                assert mod['name'] in mods, "Cannot locate mod "+mod['name']
                mod_versions = mods[mod['name']]
                if 'version' in mod:
                    assert mod['version'] in mod_versions,\
                        "Cannot locate mod "+mod['name']+" with version "+mod['version']
                    enabled_mods[mod['name']] = mod_versions[mod['version']]
                else:
                    latest_version = "0.0.0"
                    for version in mod_versions:
                        if Mod.version_compare(latest_version, version) < 0:
                            latest_version = version
                    enabled_mods[mod['name']] = mod_versions[latest_version]

        return enabled_mods

    @staticmethod
    def resolve_dependency(mods):
        tier = {name: -1 for name in mods}

        def resolve(mod_name):
            tier[mod_name] = -2
            highest_dep = -1
            for dep in mods[mod_name].info['dependencies']:
                match = re.match('^(?:(\\?|\\(\\?\\)|!) *)?(.+?)(?: *([<>=]=?) *([0-9.]+))?$', dep)
                type_ = match.group(1)
                name = match.group(2)
                sense = match.group(3)
                bound = match.group(4)
                present = None
                if name in mods:
                    present = mods[name]
                    if sense is not None and bound is not None:
                        if '<' in sense and '=' in sense:
                            if Mod.version_compare(present.info['version'], bound) > 0:
                                present = None
                        elif '>' in sense and '=' in sense:
                            if Mod.version_compare(present.info['version'], bound) < 0:
                                present = None
                        elif '<' in sense:
                            if Mod.version_compare(present.info['version'], bound) >= 0:
                                present = None
                        elif '>' in sense:
                            if Mod.version_compare(present.info['version'], bound) <= 0:
                                present = None
                        else:
                            if Mod.version_compare(present.info['version'], bound) != 0:
                                present = None
                if type_ is None:
                    type_ = ''
                assert '!' not in type_ or present is None, "Dependency not satisfied "+dep
                assert '!' in type_ or '?' in type_ or present is not None, "Dependency not satisfied "+dep
                if present is not None:
                    assert tier[name] != -2, "Circular dependency"
                    if tier[name] == -1:
                        resolve(name)
                    highest_dep = max(highest_dep, tier[name])
            tier[mod_name] = highest_dep + 1

        def natural_sort(list, key=lambda s: s):
            def get_alphanum_key_func(key):
                convert = lambda text: int(text) if text.isdigit() else text.upper()
                return lambda s: [convert(c) for c in re.split('([0-9]+)', key(s))]
            sort_key = get_alphanum_key_func(key)
            list.sort(key=sort_key)

        for name in mods:
            if tier[name] == -1:
                resolve(name)
        tier['core'] = -1
        sorted_mods = list(mods.keys())
        natural_sort(sorted_mods, key=lambda n: str(tier[n]+1)+n.lstrip())
        return sorted_mods


class PropertyTree:
    @staticmethod
    def load_bool(fd):
        value = fd.read(1)
        return struct.unpack('?', value)[0]

    @staticmethod
    def load_number(fd):
        value = fd.read(8)
        return struct.unpack('d', value)[0]

    @staticmethod
    def load_string(fd):
        empty = fd.read(1)
        empty = struct.unpack('?', empty)[0]
        if empty:
            return ''
        length = fd.read(1)
        length = struct.unpack('B', length)[0]
        if length == 255:
            length = fd.read(4)
            length = struct.unpack('I', length)[0]
        value = fd.read(length)
        value = value.decode('utf-8-sig')
        return value

    @staticmethod
    def load_list(fd):
        length = fd.read(4)
        length = struct.unpack('I', length)[0]
        value = []
        for i in range(length):
            value.append(PropertyTree.load_property_tree(fd))
        return value

    @staticmethod
    def load_dict(fd):
        length = fd.read(4)
        length = struct.unpack('I', length)[0]
        value = {}
        for i in range(length):
            key = PropertyTree.load_string(fd)
            value[key] = PropertyTree.load_property_tree(fd)
        return value

    @staticmethod
    def load_property_tree(fd):
        tree_type = fd.read(2)
        tree_type = struct.unpack('Bx', tree_type)[0]
        if tree_type == 0:
            return None
        elif tree_type == 1:
            return PropertyTree.load_bool(fd)
        elif tree_type == 2:
            return PropertyTree.load_number(fd)
        elif tree_type == 3:
            return PropertyTree.load_string(fd)
        elif tree_type == 4:
            return PropertyTree.load_list(fd)
        elif tree_type == 5:
            return PropertyTree.load_dict(fd)
        else:
            print('Unrecognized type in property tree: ' + tree_type)

    @staticmethod
    def load_mod_settings(path):
        with open(path, 'rb') as f:
            version = f.read(9)
            version = struct.unpack('HHHHx', version)
            return PropertyTree.load_property_tree(f)


class LuaLoader:
    def __init__(self, mod_manager, mod_settings):
        self.package = None
        self.current_path = None
        self.mod_manager = mod_manager
        self.mod_settings = mod_settings
        self.lua = lupa.LuaRuntime()
        self.lua.execute('function math.pow(x,y) return x^y end')
        serpent = self.lua.require('serpent')
        self.lua.globals().serpent = serpent
        self.lua.execute('function table_size(t)\n'
                         '  local count = 0\n'
                         '  for k,v in pairs(t) do\n'
                         '    count = count + 1\n'
                         '  end\n'
                         '  return count\n'
                         'end')
        self.lua.execute('function log(s)\n'
                         '  print(s)\n'
                         'end')
        self.lua.execute('package={loaded={}}')

        defines = self.lua.require('defines')
        self.lua.globals().defines = defines

        closure = self.lua.eval('function (obj) return function (f) return obj:require(f) end end')
        self.lua.globals().require = closure(self)

        self.push_mods()
        self.push_mod_settings()

        with self.mod_manager.mods['core'].get_file('lualib/dataloader.lua') as f:
            file = f.read()
            self.lua.eval('function(s) return load(s)() end')(file)

        self.load_mods()

    def require(self, module):
        if self.lua.globals().package.loaded[module] is not None:
            return self.lua.globals().package.loaded[module]
        saved_package = self.package
        saved_path = self.current_path
        origin_name = module
        if module.startswith('__'):
            self.package = re.split('[./]', module)[0]
            assert self.package.endswith('__'), self.package
            self.package = self.package[2:-2]
            module = '.'.join(re.split('[./]', module)[1:])
        else:
            if module.startswith('.'):
                module = module[1:]
            relative_module = module if self.current_path == '' else self.current_path+'.'+module
            if self.mod_manager.mods[self.package].exists('/'.join(relative_module.split('.')) + '.lua'):
                module = relative_module
            elif not self.mod_manager.mods[self.package].exists('/'.join(module.split('.')) + '.lua'):
                self.package = 'core'
                module = 'lualib.' + module

        self.current_path = '.'.join(module.split('.')[:-1])
        module = '/'.join(module.split('.')) + '.lua'

        assert(self.mod_manager.mods[self.package].exists(module))
        with self.mod_manager.mods[self.package].get_file(module) as f:
            file = f.read()

        eval_result = self.lua.eval('function(s) return load(s)() end')(file)
        if eval_result is None:
            eval_result = True
        self.lua.globals().package.loaded[origin_name] = eval_result

        self.package = saved_package
        self.current_path = saved_path

        return eval_result

    def push_mods(self):
        mods = {}
        for m in self.mod_manager.mods:
            mods[m] = '0.0.0' if m == 'core' else self.mod_manager.mods[m].info['version']
        self.lua.globals().mods = self.lua.table_from(mods)

    def push_mod_settings(self):
        self.lua.globals().settings = self.lua.table_from(self.mod_settings)

    def load_mods(self):
        for stage in 'data', 'data-updates', 'data-final-fixes':
            for mod_name in self.mod_manager.mod_order:
                mod = self.mod_manager.mods[mod_name]
                if mod.exists(stage + '.lua'):
                    version = '0.0.0' if mod_name == 'core' else mod.info['version']
                    print('Loading mod '+mod_name+' '+version+' ('+stage+'.lua)')
                    self.package = mod_name
                    self.current_path = ''
                    with mod.get_file(stage + '.lua') as f:
                        file = f.read()
                        self.lua.eval('function(s) return load(s)() end')(file)
                    self.lua.execute('package.loaded = {}')

    def get_dataraw(self):
        return self.lua.globals().data.raw


class LocaleProvider:
    def __init__(self, current, default, mod_manager):
        self.current_locale = current
        self.default_locale = default
        self.mod_manager = mod_manager
        self.current_values = self.load_locale(current)
        self.default_values = self.load_locale(default)

    def load_locale(self, locale):
        values = {}
        for mod_name in self.mod_manager.mod_order:
            mod = self.mod_manager.mods[mod_name]
            if mod.exists('locale/'+locale+'/'):
                for cfg in mod.listdir('locale/'+locale):
                    if cfg.endswith('.cfg'):
                        with mod.get_file(cfg) as f:
                            env = ''
                            for line in f:
                                line = line.strip()
                                if line.startswith('['):
                                    assert line.endswith(']')
                                    env = line[1:-1]+'.'
                                elif '=' in line:
                                    key = line.split('=')[0]
                                    key = env + key
                                    value = '='.join(line.split('=')[1:])
                                    value = value.replace('\\n', '\n')
                                    if key not in values:
                                        values[key] = value
        return values

    def localise_string(self, t):
        if type(t) == dict or lupa.lua_type(t) == 'table':
            key = t[1]
            params = [self.localise_string(t[i+2]) for i in range(len(t)-1)]
            if key == '':
                return ''.join(params)
            if key in self.current_values:
                template = self.current_values[key]
            elif key in self.default_values:
                template = self.default_values[key]
            else:
                template = 'Unknown key:"'+key+'"'

            def plural_replacer(match):
                index = int(match.group(1))
                number = int(params[index-1])
                patterns = match.group(2)
                patterns = patterns.split('|')

                for pattern in patterns:
                    rules = pattern.split('=')[0]
                    result = '='.join(pattern.split('=')[1:])
                    for rule in rules.split(','):
                        if rule.startswith('ends in '):
                            tail = rule[len('ends in '):]
                            if str(number).endswith(tail):
                                return result
                        elif rule == 'rest':
                            return result
                        elif rule == str(number):
                            return result
                return "Unknown plural for number " + str(number)

            def argument_replacer(match):
                index = int(match.group(1))
                return params[index-1]

            template = re.sub("__plural_for_parameter_([0-9]+)_\{([^}]*)\}__",
                              plural_replacer,
                              template)
            template = re.sub("__([0-9]+)__",
                              argument_replacer,
                              template)
            return template
        else:
            return str(t)



