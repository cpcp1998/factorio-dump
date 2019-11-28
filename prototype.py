import math
import re
import struct
import collections
import lupa
from PIL import Image, ImageChops, PngImagePlugin, ImageFile


# hack the crc check so that angels bio processing can load
def crc(self, cid, data):
    """Read and verify checksum"""

    # Skip CRC checks for ancillary chunks if allowed to load truncated
    # images
    # 5th byte of first char is 1 [specs, section 5.4]
    if ImageFile.LOAD_TRUNCATED_IMAGES and (PngImagePlugin.i8(cid[0]) >> 5 & 1):
        self.crc_skip(cid, data)
        return

    try:
        crc1 = PngImagePlugin._crc32(data, PngImagePlugin._crc32(cid))
        crc2 = PngImagePlugin.i32(self.fp.read(4))
        #if crc1 != crc2:
        #    raise SyntaxError("broken PNG file (bad header checksum in %r)"
        #                      % cid)
    except struct.error:
        raise SyntaxError("broken PNG file (incomplete checksum in %r)"
                          % cid)


PngImagePlugin.ChunkStream.crc = crc


class IconLoader:
    def __init__(self, mod_manager):
        self.mod_manager = mod_manager

    def get_raw_icon(self, prototype, expected_size):
        file = prototype.icon
        assert file is not None
        mod = file.split('/')[0]
        assert mod.startswith('__') and mod.endswith('__')
        mod = mod[2:-2]
        file = '/'.join(file.split('/')[1:])
        with self.mod_manager.mods[mod].get_binary(file) as f:
            with PngImagePlugin.Image.open(f, 'r') as im_file:
                im = im_file.convert('RGBA')
        if prototype.tint is not None:
            red = prototype.tint.r or prototype.tint[1] or 0
            green = prototype.tint.g or prototype.tint[2] or 0
            blue = prototype.tint.b or prototype.tint[3] or 0
            alpha = prototype.tint.a
            if alpha is None:
                alpha = prototype.tint[4]
            if alpha is None:
                alpha = 1
            if red <= 1 and green <= 1 and blue <= 1 and alpha <= 1:
                red, green, blue, alpha = red*255, green*255, blue*255, alpha*255
            red, green, blue, alpha = int(red), int(green), int(blue), int(alpha)
            multiplier = Image.new('RGBA', im.size, (red, green, blue))
            multiplier.putalpha(alpha)
            im = ImageChops.multiply(im, multiplier)
        if prototype.scale is not None:
            scale = prototype.scale
            im = im.resize((int(im.width*scale), int(im.height*scale)), resample=Image.LANCZOS)
        else:
            im = im.resize((expected_size, expected_size), resample=Image.LANCZOS)
        if prototype.shift is not None:
            shift = (prototype.shift[1], prototype.shift[2])
        elif prototype.scale is not None:
            shift = (0, 0)
        else:
            shift = None
        if shift is not None:
            shift = (int(shift[0]+(expected_size-im.width)/2), int(shift[1]+(expected_size-im.height)/2))
            empty = Image.new('RGBA', (expected_size, expected_size), (255, 255, 255))
            empty.putalpha(0)
            empty.paste(im, shift)
            im = empty
        return im

    def get_icon(self, prototype, expected_size):
        if prototype.icon is not None:
            return self.get_raw_icon(prototype, expected_size)
        im = Image.new('RGBA', (expected_size, expected_size), (255, 255, 255))
        im.putalpha(0)
        for p in range(len(prototype.icons)):
            im = Image.alpha_composite(im, self.get_raw_icon(prototype.icons[p+1], expected_size))
        return im

    @staticmethod
    def get_atlas(icons, icon_size):
        width = math.ceil(math.sqrt(len(icons)))
        height = math.ceil(len(icons) / width)
        atlas = Image.new('RGBA', (width*icon_size, height*icon_size), (255, 255, 255))
        atlas.putalpha(0)
        mapping = {}
        x = y = 0
        for item in icons:
            icon = icons[item]
            atlas.paste(icon, (x*icon_size, y*icon_size))
            mapping[item] = (x, y)
            if x == width - 1:
                x, y = 0, y+1
            else:
                x += 1
        background = Image.new('RGBA', (width * icon_size, height * icon_size), (127, 127, 127))
        background.putalpha(0)
        atlas = Image.alpha_composite(background, atlas)
        return atlas, mapping


class Prototype:
    icons = None
    icon_size = 32

    def __init__(self, prototype):
        self.type = prototype.type
        self.name = prototype.name
        self.order = self._get_str(prototype.order, '')
        assert self.type is not None
        assert self.name is not None
        self.localised_name = prototype.localised_name

    def __lt__(self, other):
        if self.order == other.order:
            return self.name < other.name
        return self.order < other.order

    @staticmethod
    def _get_difficulty(prototype, difficulty):
        assert difficulty == 'normal' or difficulty == 'expensive'
        if prototype.normal is None and prototype.expensive is None:
            return prototype, True
        if prototype[difficulty] is not None and prototype[difficulty] is not False:
            return prototype[difficulty], True
        difficulty = 'normal' if difficulty == 'expensive' else 'expensive'
        return prototype[difficulty], False

    @staticmethod
    def _get_bool(prototype, default):
        if prototype is None:
            return default
        if type(prototype) is str:
            assert prototype == 'true' or prototype == 'false'
            return prototype == 'true'
        assert type(prototype) is bool
        return prototype

    @staticmethod
    def _get_int(prototype, default):
        if prototype is None:
            return default
        return int(prototype)

    @staticmethod
    def _get_float(prototype, default):
        if prototype is None:
            return default
        return float(prototype)

    @staticmethod
    def _get_str(prototype, default):
        if prototype is None:
            return default
        return str(prototype)

    def get_localised_name(self, locale_provider):
        return locale_provider.localise_string(self.localised_name)

    @classmethod
    def get_atlas(cls):
        return IconLoader.get_atlas(cls.icons, cls.icon_size)


class ItemGroup(Prototype):
    icons = {}
    icon_size = 64

    def __init__(self, prototype, icon_loader):
        super().__init__(prototype)
        ItemGroup.icons[self.name] = icon_loader.get_icon(prototype, 64)
        if self.localised_name is None:
            self.localised_name = {1: 'item-group-name.' + self.name}
        self.order_in_recipe = self._get_str(prototype.order_in_recipe, self.order)


class ItemSubGroup(Prototype):
    def __init__(self, prototype):
        super().__init__(prototype)
        self.group = prototype.group


class Item(Prototype):
    icons = {}
    icon_size = 32

    def __init__(self, prototype, icon_loader):
        super().__init__(prototype)
        self.subgroup = self._get_str(prototype.subgroup, 'other')
        Item.icons[self.name] = icon_loader.get_icon(prototype, 32)
        if self.localised_name is None:
            if prototype.place_result is not None:
                self.localised_name = {1: 'entity-name.'+prototype.place_result}
            elif prototype.placed_as_equipment_result is not None:
                self.localised_name = {1: 'equipment-name.' + prototype.placed_as_equipment_result}
            else:
                self.localised_name = {1: 'item-name.' + self.name}


class Fluid(Prototype):
    icons = {}
    icon_size = 32

    def __init__(self, prototype, icon_loader):
        super().__init__(prototype)
        self.subgroup = self._get_str(prototype.subgroup, 'fluid')
        Fluid.icons[self.name] = icon_loader.get_icon(prototype, 32)
        self.default_temperature = prototype.default_temperature
        self.max_temperature = prototype.max_temperature
        if self.localised_name is None:
            self.localised_name = {1: 'fluid-name.' + self.name}
        # the following two fields are reserved for resolving temperature
        self.available_temperatures = None
        self.temperature_groups = None


class Entity(Prototype):
    icons = {}
    icon_size = 32

    def __init__(self, prototype, icon_loader):
        super().__init__(prototype)
        Entity.icons[self.name] = icon_loader.get_icon(prototype, 32)
        if self.localised_name is None:
            self.localised_name = {1: 'entity-name.' + self.name}


class Technology(Prototype):
    icons = {}
    icon_size = 128

    def __init__(self, prototype, icon_loader, difficulty):
        super().__init__(prototype)
        Technology.icons[self.name] = icon_loader.get_icon(prototype, 128)
        match = re.match("^(.*)-(\\d+)$", self.name)
        if match:
            self.raw_name = match.group(1)
            self.level = int(match.group(2))
        else:
            self.raw_name = self.name
            self.level = 0
        tech_data = Prototype._get_difficulty(prototype, difficulty)[0]
        if self.localised_name is None:
            if self.raw_name == self.name:
                self.localised_name = {1: 'technology-name.' + self.raw_name}
            elif tech_data.max_level is None or tech_data.max_level == self.level:
                self.localised_name = {1: '', 2: {1: 'technology-name.' + self.raw_name}, 3: ' '+str(self.level)}
            else:
                self.localised_name = {1: 'technology-name.' + self.raw_name}
        self.enabled = self._get_bool(tech_data.enabled, True)
        self.max_level = tech_data.max_level
        self.prerequisites = set((tech_data.prerequisites or {}).values())
        self.unlocks = [m.recipe for m in (tech_data.effects or {}).values() if m.type == 'unlock-recipe']


class Product:
    def __init__(self, prototype, fluids):
        if type(prototype) == dict:
            self.type = 'item'
            self.name = prototype['name']
            self.amount = prototype['amount']
            self.temperature = None
        else:
            self.type = prototype.type or 'item'
            if prototype[1] is not None:
                assert prototype[2] is not None or prototype.amount is not None
                self.name = prototype[1]
                self.amount = prototype[2]
                if self.amount is None:
                    self.amount = prototype.amount
            else:
                self.name = prototype.name
                if prototype.amount is not None:
                    self.amount = prototype.amount
                else:
                    self.amount = (prototype.amount_min+prototype.amount_max)/2
                if prototype.probability is not None:
                    self.amount *= prototype.probability
            self.temperature = prototype.temperature
            if self.temperature is None and self.type == 'fluid':
                self.temperature = fluids[self.name].default_temperature


class Ingredient:
    def __init__(self, prototype, fluids):
        self.type = prototype.type or 'item'
        if prototype[1] is not None:
            assert prototype[2] is not None or prototype.amount is not None
            self.name = prototype[1]
            self.amount = prototype[2]
            if self.amount is None:
                self.amount = prototype.amount
        else:
            self.name = prototype.name
            self.amount = prototype.amount
        if prototype.temperature is not None:
            self.minimum_temperature = prototype.temperature
            self.maximum_temperature = prototype.temperature
        else:
            self.minimum_temperature = prototype.minimum_temperature
            self.maximum_temperature = prototype.maximum_temperature
        if self.minimum_temperature is None and self.type == 'fluid':
            self.minimum_temperature = fluids[self.name].default_temperature
        if self.maximum_temperature is None and self.type == 'fluid':
            self.maximum_temperature = fluids[self.name].max_temperature


class Recipe(Prototype):
    icons = {}
    icon_size = 32

    def __init__(self, prototype, icon_loader, difficulty, items, fluids):
        super().__init__(prototype)
        self.category = self._get_str(prototype.category, 'crafting')
        recipe_data, enabled = Prototype._get_difficulty(prototype, difficulty)
        self.enabled = self._get_bool(recipe_data.enabled, True)
        self.enabled = self.enabled and enabled
        self.main_product = recipe_data.main_product
        self.ingredients = [Ingredient(i, fluids) for i in recipe_data.ingredients.values()]
        if recipe_data.results is not None:
            self.results = [Product(i, fluids) for i in recipe_data.results.values()]
        else:
            self.results = [Product({'name': recipe_data.result, 'amount': self._get_float(recipe_data.result_count, 1)}, fluids)]
        self.energy_required = recipe_data.energy_required or 0.5
        if self.main_product is None and len(self.results) == 1:
            self.main_product = self.results[0].name
        if self.main_product is not None:
            for result in self.results:
                if result.name == self.main_product:
                    self.main_product_type = result.type
        if self.localised_name is None:
            if self.main_product is not None and self.main_product != '':
                if self.main_product_type == 'item':
                    self.localised_name = items[self.main_product].localised_name
                else:
                    self.localised_name = fluids[self.main_product].localised_name
            else:
                self.localised_name = {1: 'recipe-name.'+self.name}
        if self.main_product == '':
            self.main_product = None
        if prototype.icon is not None or prototype.icons is not None:
            Recipe.icons[self.name] = icon_loader.get_icon(prototype, 32)
        else:
            assert self.main_product is not None
            if self.main_product_type == 'item':
                Recipe.icons[self.name] = Item.icons[self.main_product]
            else:
                Recipe.icons[self.name] = Fluid.icons[self.main_product]
        self.subgroup = prototype.subgroup
        if self.subgroup is None:
            assert self.main_product is not None
            if self.main_product_type == 'item':
                self.subgroup = items[self.main_product].subgroup
            else:
                self.subgroup = fluids[self.main_product].subgroup
        if self.order == '' and self.main_product is not None:
            if self.main_product_type == 'item':
                self.order = items[self.main_product].order
            else:
                self.order = fluids[self.main_product].order


class Resource(Entity):
    def __init__(self, prototype, icon_loader, fluids):
        super().__init__(prototype, icon_loader)
        self.infinite = self._get_bool(prototype.infinite, False)
        self.category = self._get_str(prototype.category, "basic-solid")
        self.mining_time = prototype.minable.mining_time
        self.fluid_amount = prototype.minable.fluid_amount or 0
        self.required_fluid = prototype.minable.required_fluid
        if prototype.minable.results is not None:
            self.results = [Product(i, fluids) for i in prototype.minable.results.values()]
        else:
            self.results = [Product({'name': prototype.minable.result, 'amount': self._get_float(prototype.minable.count, 1)}, fluids)]


class MiningDrill(Entity):
    def __init__(self, prototype, icon_loader):
        super().__init__(prototype, icon_loader)
        self.speed = prototype.mining_speed
        self.categories = list(prototype.resource_categories.values())
        self.input_fluid_box = 0 if prototype.input_fluid_box is None else 1
        self.output_fluid_box = 0 if prototype.output_fluid_box is None else 1
        if prototype.allowed_effects is not None:
            self.allowed_effects = list(prototype.allowed_effects.values())
        else:
            self.allowed_effects = ["speed", "productivity", "consumption", "pollution"]
        if prototype.module_specification is not None:
            self.module_slots = prototype.module_specification.module_slots or 0
        else:
            self.module_slots = 0
        self.base_productivity = 0


class CraftingMachine(Entity):
    def __init__(self, prototype, icon_loader):
        super().__init__(prototype, icon_loader)
        self.speed = prototype.crafting_speed
        self.categories = list(prototype.crafting_categories.values())
        if prototype.allowed_effects is not None:
            self.allowed_effects = list(prototype.allowed_effects.values())
        else:
            self.allowed_effects = []
        if prototype.module_specification is not None:
            self.module_slots = prototype.module_specification.module_slots or 0
        else:
            self.module_slots = 0
        self.input_fluid_box = 0
        self.output_fluid_box = 0
        if prototype.fluid_boxes is not None:
            for box in prototype.fluid_boxes.values():
                if lupa.lua_type(box) == 'table':
                    if 'input' == box.production_type:
                        self.input_fluid_box += 1
                    elif 'output' == box.production_type:
                        self.output_fluid_box += 1
        self.ingredient_count = self._get_int(prototype.ingredient_count, self._get_int(prototype.source_inventory_size, -1))
        self.fixed_recipe = self._get_str(prototype.fixed_recipe, "")
        self.base_productivity = self._get_float(prototype.base_productivity, 0)


class OffshorePump(Entity):
    def __init__(self, prototype, icon_loader):
        super().__init__(prototype, icon_loader)
        self.fluid = prototype.fluid
        self.pumping_speed = prototype.pumping_speed


class Module(Item):
    def __init__(self, prototype, icon_loader):
        super().__init__(prototype, icon_loader)
        self.category = prototype.category
        self.tier = prototype.tier
        self.effects = collections.defaultdict(float)
        for type_ in prototype.effect:
            effect = prototype.effect[type_].bonus
            self.effects[type_] = effect
        if prototype.limitation is not None:
            self.limitation = list(prototype.limitation.values())
        else:
            self.limitation = []
