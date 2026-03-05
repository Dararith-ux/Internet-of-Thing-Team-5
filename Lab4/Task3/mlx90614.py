from machine import I2C

class MLX90614:
    def __init__(self, i2c, address=0x5A):
        self.i2c = i2c
        self.address = address

    def read16(self, reg):
        data = self.i2c.readfrom_mem(self.address, reg, 3)
        return data[0] | (data[1] << 8)

    def read_temp(self, reg):
        temp = self.read16(reg)
        return (temp * 0.02) - 273.15

    def read_ambient_temp(self):
        return self.read_temp(0x06)

    def read_object_temp(self):
        return self.read_temp(0x07)



